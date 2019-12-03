#!/usr/bin/env python3

# Copyright 2019 Paul S. Strauss

#=============================================================================
# Parses XML output from Doxygen to discover direct class dependencies. This
# can be useful for languages such as C# that do not declare dependencies in
# #include statements.
#
# Class C1 has a direct dependency on class C2 if any of the following is true:
#   - C1 is derived directly from C2.
#   - C2 is a nested class inside C1.
#   - C1 has a member variable of type C2.
#   - C1 has a member function with any parameter of type C2.
#   - C2 has a member function that is called by code in C1.
#
# This assumes the entire XML tree will fit in memory, so it may not work for
# very large projects.
#
# TODO: Do a real graph traversal to find all cycles.
#=============================================================================

from argparse import ArgumentParser

DEFAULT_OUTPUT_FILE_NAME = 'doxdepends.dot'

#-----------------------------------------------------------------------------
# Command-line argument processing.
#-----------------------------------------------------------------------------

def ProcessArguments():
    description = (
        """Parses XML output from Doxygen to discover class dependencies, then
        outputs a graph in dot format that can be added to Doxygen
        documentation using the \dotfile special command. If classes are defined
        as parts of Doxygen groups, those groups are represented as clusters in
        the dependency graph.
        """)
    parser = ArgumentParser(description=description)
    parser.add_argument(
        '-c', '--report_cycles', action='store_true', dest='report_cycles',
        default=False,
        help="""Prints information about dependency cycles between classes to
        standard output""")
    parser.add_argument(
        '-n', '--target_namespace', default=None,
        help="""Specifies a target namespace for the graph. Any code entity
        within that namespace will have its namespace prefix (such as
        "MyProject::") removed in the graph. Furthermore, entities in other
        namespaces will not appear in the graph.""")
    parser.add_argument(
        '-o', '--output_file', default=DEFAULT_OUTPUT_FILE_NAME,
        help="""Specifies the output file containing the dot graph. Defaults to
        "%(default)s" if not specified.""")
    parser.add_argument(
        '-v', '--verbose', action='store_true', dest='verbose', default=False,
        help='Print verbose progress information during processing')
    parser.add_argument(
        'xml_directory',
        help="""The directory containing the XML specification produced by
        Doxygen for the project.""")
    return parser

#-----------------------------------------------------------------------------
# This class does all of the processing to produce the dependency graph.
#-----------------------------------------------------------------------------

class Grapher(object):
    """Processes XML output produced by Doxygen for a project and produces a
    Dot graph representing dependencies between the classes and structs in the
    project.

    Every entity in Doxygen's XML has a reference id ("refid") that identifies
    it uniquely. These refids are used as keys in dictionaries to refer to
    those entities.

    Note that the word "class" used in any comment should be interpreted as
    "class, struct, or interface".
    """

    # ---------------- Public interface.

    def __init__(self, is_verbose):
        self._is_verbose = is_verbose

        # These are set in ProcessXML().
        self._xml_directory    = None
        self._target_namespace = None

        # Dictionary storing class and group names keyed by refid.
        self._ref_dict = {}

        # Dictionary storing dependencies for a class, keyed by the refid of
        # the class. The value is a Set of refids of classes it depends on.
        self._dep_dict = {}

        # Dictionary storing nested class relationships. If class C has a
        # nested class N, then there will be an entry keyed by N's refid with
        # the value of C's refid.
        self._nested_dict = {}

        # Dictionary storing group information for each class, keyed by the
        # refid of the class. The value is the refid of group it belongs to.
        # This assumes a class belongs to at most one group.
        self._group_dict = {}

    def ProcessXML(self, xml_directory, target_namespace):
        """Processes the Doxygen-produced XML files in the given directory"""
        self._xml_directory    = xml_directory
        self._target_namespace = target_namespace

        if self._is_verbose:
            print('=== Using XML_DIRECTORY "%s"' % xml_directory)

        # The starting point for the XML data is always "index.xml".
        self._ProcessIndexFile('index.xml')

    def ReportCycles(self):
        """Reports any cycles found during processing of the XML files."""
        # Note: this finds only cycles of size 2.
        for (key, value) in self._dep_dict.items():
            for dep in value:
                if dep in self._dep_dict and key in self._dep_dict[dep]:
                    print('*** Cycle between %s and %s' %
                          (self._ref_dict[key], self._ref_dict[dep]))


    def OutputDotGraph(self, output_file):
        # Recursively discover groups for nested classes.
        self._FindNestedClassGroups()

        # Get a dictionary of all groups.
        subgraph_dict = self._GetSubgraphDict()

        # Collect all groups, other classes, and dependencies.
        groups            = self._CollectGroups(subgraph_dict)
        ungrouped_classes = self._CollectUngroupedClasses(subgraph_dict)
        dependencies      = self._CollectDependencies()

        writer = Writer(output_file)
        writer.Write(groups, ungrouped_classes, dependencies)

    # ---------------- Implementation.

    def _ProcessIndexFile(self, file_name):
        root = self._ParseXMLFile(file_name, 'index')
        if not root:
            return
        for compound in root.findall('compound'):
            refid = compound.get('refid')
            kind  = compound.get('kind')
            name  = compound.findtext('name')
            if kind in ['class', 'struct', 'interface', 'group']:
                # Store entity name indexed by refid in _ref_dict.
                self._ref_dict[refid] = name
                # Handle groups specially.
                if kind == 'group':
                    self._ProcessGroupFile(refid)
                # Don't process entities in other namespaces
                elif self._IncludeName(name):
                    self._ProcessClassFile(refid, kind)

    def _ProcessGroupFile(self, refid):
        """Processes an XML file representing a Doxygen group. The file name is
        created from the given group refid."""
        root = self._ParseXMLFile(refid + '.xml', 'group')
        if not root:
            return
        # Add classes belonging to the group to _group_dict.
        for innerclass in root.findall('compounddef/innerclass'):
            self._group_dict[innerclass.get('refid')] = refid

    def _ProcessClassFile(self, refid, kind):
        """Processes an XML file representing a Doxygen class, struct, or
        interface. The file name is created from the given class refid."""
        root = self._ParseXMLFile(refid + '.xml', kind)
        if not root:
            return

        # Add dependencies on base classes.
        for baseref in root.findall('compounddef/basecompoundref'):
            name = baseref.text
            if name is not None and self._IncludeName(name):
                self._AddDependency(refid, baseref.get('refid'))

        # Add dependencies on nested classes; also add to _nested_dict.
        for innerclass in root.findall('compounddef/innerclass'):
            inner_refid = innerclass.get('refid')
            self._AddDependency(refid, inner_refid)
            self._nested_dict[inner_refid] = refid

        # Look for member variables and functions.
        for member in root.findall('compounddef/sectiondef/memberdef'):
            self._ProcessClassMember(refid, member)

    def _ProcessClassMember(self, class_refid, member):
        kind  = member.get('kind')
        refid = self._GetTypeRefID(member)
        # Look at only variables and function parameters, assuming properties
        # are not classes or structs.
        if kind == 'variable':
            if refid is not None:
                self._AddDependency(class_refid, refid)
        elif kind == 'function':
            if refid is not None:
                self._AddDependency(class_refid, refid)
            self._ProcessClassFunction(class_refid, member)

    def _ProcessClassFunction(self, class_refid, func):
        # Add dependencies on any classes found as parameter types.
        for param in func.findall('param'):
            refid = self._GetTypeRefID(param)
            if refid:
                self._AddDependency(class_refid, refid)
        # Add dependencies on the class to entities that reference the function.
        for ref_by in func.findall('referencedby'):
            # The refid for a function is the class refid + a long unique ID
            # after the last underscore. Remove that part to get the class
            # refid.
            by_func_refid  = ref_by.get('refid')
            by_class_refid = by_func_refid.rsplit('_', 1)[0]
            self._AddDependency(by_class_refid, class_refid)

    def _ParseXMLFile(self, file_name, entity_type):
        """Parses the given XML file, returning the root ElementTree, or None
        if there is some sort of problem."""
        from os.path               import join  as joinpath
        from xml.etree.ElementTree import parse as xmlparse
        if self._is_verbose:
            print('===     Processing %s file "%s"' % (entity_type, file_name))
        path = joinpath(self._xml_directory, file_name)
        try:
            return xmlparse(path).getroot()
        except:
            print('*** Unable to parse XML from "%s"' % path)
            return None

    def _IncludeName(self, name):
        """Returns True if the given name should be included in the output,
        meaning it is in the correct namespace."""
        return (self._target_namespace is None or
                name.startswith(self._target_namespace + '::') or
                name.startswith(self._target_namespace + '.'))

    def _GetShortName(self, full_name):
        if (self._target_namespace is not None and
            full_name.startswith(self._target_namespace + '::')):
            return full_name.replace(self._target_namespace + '::', '')
        else:
            return full_name

    def _GetTypeRefID(self, element):
        """Returns the refid for an element if it has a "type" subelement with
        a "ref" subelement inside it. Otherwise, returns None"""
        ref = element.find('type/ref')
        if ref is not None:  # For some reason, 'if ref:' does not work!
            return ref.get('refid')
        return None

    def _AddDependency(self, from_refid, to_refid):
        """Adds a dependency from the entity with from_refid to the one with
        to_refid"""
        # Ignore self-dependencies, which are not very useful to display.
        if from_refid != to_refid:
            self._dep_dict[from_refid] = self._dep_dict.get(from_refid, set())
            self._dep_dict[from_refid].add(to_refid)

    def _GetDependencies(self, refid):
        """Reurns a sorted list of items the item with the given refid depends
        on."""
        deps = [dep for dep in self._dep_dict[refid] if dep in self._ref_dict]
        return ' '.join(sorted(['"%s"' % self._GetShortName(self._ref_dict[dep])
                                for dep in deps]))

    def _FindNestedClassGroups(self):
        """Looks for classes nested inside another class that is a member of a
        group, adding the nested ones to the same group."""
        def _GetGroup(refid):
            if refid is None:
                return None
            return (self._group_dict.get(refid) or
                    _GetGroup(self._nested_dict.get(refid)))

        for inner_refid, outer_refid in self._nested_dict.items():
            group_refid = _GetGroup(outer_refid)
            if group_refid is not None:
                self._group_dict[inner_refid] = group_refid

    def _GetSubgraphDict(self):
        """Reverses _group_dict to get the members of all groups, which become
        cluster subgraphs in the Dot output."""
        subgraph_dict = {}
        for k, v in self._group_dict.items():
            subgraph_dict[v] = subgraph_dict.get(v, [])
            subgraph_dict[v].append(k)
        return subgraph_dict

    def _CollectGroups(self, subgraph_dict):
        """Returns a list of Writer.Group instances representing all groups."""
        groups = []
        for group in sorted(subgraph_dict.keys()):
            group_name = self._ref_dict[group]
            member_classes = []
            for member in sorted(subgraph_dict[group]):
                name = self._ref_dict[member]
                if self._IncludeName(name):
                    member_classes.append(
                        Writer.Class(self._GetShortName(name), name))
            groups.append(Writer.Group(group_name, member_classes))
        return groups

    def _CollectUngroupedClasses(self, subgraph_dict):
        """Returns a list of Writer.Class instances representing all classes
        not inside groups."""
        classes = []
        for refid in sorted(self._ref_dict.keys()):
            if refid in subgraph_dict:  # In a group, so skip it.
                continue
            name = self._ref_dict[refid]
            if self._IncludeName(name):
                classes.append(Writer.Class(self._GetShortName(name), name))
        return classes

    def _CollectDependencies(self):
        """Returns a list of Writer.Dependencies instances representing all
        class-to-class dependencies."""
        dependencies = []
        for refid in sorted(self._dep_dict.keys()):
            name = self._GetShortName(self._ref_dict[refid])
            # Access all items in _dep_dict for the refid if the item appears
            # in the _ref_dict. Convert them to short names for labels.
            deps = [self._GetShortName(self._ref_dict[dep])
                    for dep in self._dep_dict[refid] if dep in self._ref_dict]
            dependencies.append(Writer.Dependencies(name, sorted(deps)))
        return dependencies

#-----------------------------------------------------------------------------
# This class handles output.
#-----------------------------------------------------------------------------

class Writer(object):
    # ---------------- Nested classes used in the interface.

    class Class(object):
        """Represents a class, struct, or interface to output."""

        def __init__(self, label, url_ref):
            """Initializes given the label for the class in the graph and the
            target of the Doxygen \ref command for the URL to link to."""
            self.label   = label
            self.url_ref = url_ref

    class Group(object):
        """Represents a Group to write out."""

        def __init__(self, label, member_classes):
            """Initializes given the label for the group's cluster and the
            member classes of the group (list of Class instances)."""
            self.label          = label
            self.member_classes = member_classes

    class Dependencies(object):
        """Represents dependencies of a class on other classes."""

        def __init__(self, label, dependency_labels):
            """Initializes given the label for the class cluster and a list of
            labels for the classes representing the dependencies."""
            self.label             = label
            self.dependency_labels = dependency_labels

    # ---------------- Public interface.

    def __init__(self, output_file):
        try:
            self._f = open(output_file, 'w')
        except:
            print('*** Unable to open output file "%s": aborting' % output_file)
            self._f = None

    def Write(self, groups, ungrouped_classes, dependencies):
        """Writes a graph represented by the groups, ungrouped classes, and
        dependencies to the given output file path."""
        if self._f is None:
            return
        self._WriteGraphHeader()
        for i, group in enumerate(groups):
            self._WriteGroup(group, i)
        for uclass in ungrouped_classes:
            self._WriteClass(uclass)
        for dep in dependencies:
            self._WriteDependencies(dep)
        self._WriteGraphFooter()

    # ---------------- Implementation.

    def _WriteGraphHeader(self):
        self._WriteLine('digraph dependencies {')
        self._WriteLine(' rankdir="LR";');
        self._WriteLine(' concentrate=true;')
        self._WriteLine(' node [shape=record, fontname=Verdana,' +
                        ' fontsize=10, margin=.1, width=.2, height=.2];')

    def _WriteGraphFooter(self):
        self._WriteLine('}')

    def _WriteGroup(self, group, index):
        self._WriteLine(' subgraph cluster_%d {' % index)
        self._WriteLine('   label     = "%s";' % group.label)
        self._WriteLine('   labeljust = r;')
        self._WriteLine('   color     = darkorange;')
        self._WriteLine('   fontcolor = darkorange;')
        self._WriteLine('   fontsize  = 12;')
        self._WriteLine('   fontname  = "Verdana";')
        self._WriteLine('   penwidth  = 2;')
        for member in group.member_classes:
            self._WriteClass(member, extra_indent='  ')
        self._WriteLine(' }')

    def _WriteClass(self, classs, extra_indent=''):
        self._WriteLine('%s "%s" [URL="\\ref %s", fontcolor=blue];' %
                        (extra_indent, classs.label, classs.url_ref))

    def _WriteDependencies(self, dep):
        dep_string = ' '.join(['"%s"' % dl for dl in dep.dependency_labels])
        self._WriteLine(' "%s" -> { %s };' % (dep.label, dep_string))

    def _WriteLine(self, line):
        self._f.write(line + '\n')

#-----------------------------------------------------------------------------
# Mainline.
#-----------------------------------------------------------------------------

def main():
    # Parse command-line arguments.
    parser = ProcessArguments()
    args = parser.parse_args()

    # Process the XML.
    grapher = Grapher(args.verbose)
    grapher.ProcessXML(args.xml_directory, args.target_namespace)
    if args.report_cycles:
        grapher.ReportCycles()
    grapher.OutputDotGraph(args.output_file)

if __name__ == '__main__':
    main()
