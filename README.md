# Doxdepends

Doxdepends is a Python script that parses XML output from
[Doxygen](http://www.doxygen.nl/) to discover class dependencies. It outputs a
graph in Dot format that can be added to Doxygen documentation using the
[\dotfile](http://www.doxygen.nl/manual/commands.html#cmddotfile) command.
Alternatively, [GraphViz](https://www.graphviz.org/) can be used directly to
generate an image of the graph.

This can be useful for languages that do not use `#include` statements to
declare dependencies among classes and other entities. For example, C# really
makes it difficult to know if there are any cyclic dependencies among classes
in a project, since it has very promiscuous access rules. By contrast, C++
requires all dependencies to be noted using `#include` statements, allowing
Doxygen to create a dependency graph based on them.

# Set Up

Prior to running this script, run Doxygen on your source code with the
[`GENERATE_XML` configuration variable](http://www.doxygen.nl/manual/config.html#cfg_generate_xml)
set to **YES**, then pass the resulting directory containing XML to
Doxdepends.

# Command Usage

```
usage: doxdepends.py [-h] [-c] [-n TARGET_NAMESPACE] [-o OUTPUT_FILE] [-v]
                     xml_directory

Parses XML output from Doxygen to discover class dependencies, then outputs a graph
in dot format that can be added to Doxygen documentation using the \dotfile special
command. If classes are defined as parts of Doxygen groups, those groups are
represented as clusters in the dependency graph.

positional arguments:
  xml_directory         The directory containing the XML specification produced by
                        Doxygen for the project.

optional arguments:
  -h, --help            show this help message and exit
  -c, --report_cycles   Prints information about dependency cycles between classes to
                        standard output
  -n TARGET_NAMESPACE, --target_namespace TARGET_NAMESPACE
                        Specifies a target namespace for the graph. Any code entity
                        within that namespace will have its namespace prefix (such as
                        "MyProject::") removed in the graph. Furthermore, entities in
                        other namespaces will not appear in the graph.
  -o OUTPUT_FILE, --output_file OUTPUT_FILE
                        Specifies the output file containing the dot graph. Defaults
                        to "doxdepends.dot" if not specified.
  -v, --verbose         Print verbose progress information during processing
```

## Dependencies

1. Python 3
2. Doxygen (for creating the XML input)
