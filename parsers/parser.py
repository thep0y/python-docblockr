"""Parsing Class for python files."""
import re
import sublime
from typing import Dict, List, Optional
from ..utils.log import child_logger

log = child_logger(__name__)


def split_by_commas(string):
    """Split a string by unenclosed commas.

    Splits a string by commas that are not inside of:
    - quotes
    - brackets
    Arguments:
        string {String} -- String to be split. Usuall a function parameter
            string

    Examples:
        >>> split_by_commas('foo, bar(baz, quux), fwip = "hey, hi"')
        ['foo', 'bar(baz, quux)', 'fwip = "hey, hi"']

    Returns:
        {list} List of elements in the string that were delimited by commas
    """
    out = []

    if not string:
        return out

    # the current token
    current = ""

    # characters which open a section inside which commas are not separators between different
    # arguments
    open_quotes = "\"'<({["
    # characters which close the section. The position of the character here should match the
    # opening indicator in `open_quotes`
    close_quotes = "\"'>)}]"

    matching_quote = ""
    inside_quotes = False
    is_next_literal = False

    for char in string:
        if is_next_literal:  # previous char was a \
            current += char
            is_next_literal = False
        elif inside_quotes:
            if char == "\\":
                is_next_literal = True
            else:
                current += char
                if char == matching_quote:
                    inside_quotes = False
        else:
            if char == ",":
                if len(current.strip()):
                    out.append(current.strip())
                current = ""
            else:
                current += char
                quote_index = open_quotes.find(char)
                if quote_index > -1:
                    matching_quote = close_quotes[quote_index]
                    inside_quotes = True

    if len(current.strip()):
        out.append(current.strip())
    return out


START_KEYWORD_RULES = (
    re.compile(r"^def\s+"),
    re.compile(r"^class\s+"),
    re.compile(r"^async\s+def\s+"),
)


def is_start_keyword(line: str) -> bool:
    for rule in START_KEYWORD_RULES:
        if rule.match(line):
            log.debug("the line contains a keyword: %s", rule)
            return True

    return False


def read_next_line(view: sublime.View, position: int, reverse=False):
    """Get the next line of the view.

    From the given position, will expand the region to the current line in the file,
    grab the ending (beginning if reverse) position, and add (subtract if reverse) 1
    to get the next line in the file. Will return False if the next line is either the
    beginning or the end of the file. This function is iteratable to continuously
    provide file lines
    Arguments:
        view     {sublime.View} -- View to be read
        position {Integer}      -- Position in the view

    Keyword Arguments:
        reverse {Bool} -- If false, will read to the end of the file (default False)

    Yields:
        {sublime.Region} Region of the next line.

    Returns:
        {Bool} False when at the beginning or end of the file
    """
    current_line = view.line(position)
    modifier = 1
    if reverse:
        modifier = -1

    go_on = True
    while go_on:
        next_line = current_line.begin() if reverse else current_line.end()
        next_line += modifier

        log.debug("next line -> %s", next_line)

        if reverse:
            line = view.line(next_line)
            line_str = view.substr(line).strip()
            if is_start_keyword(line_str):
                go_on = False

        # Ensure within bounds of the view
        if not (next_line < view.size() and next_line > 0):
            break

        current_line = view.line(next_line)

        yield current_line


def is_numeric(val):
    """Check if string is numeric.

    Arguments:
        val {str} -- potentially stringified number

    Returns:
        bool -- if the passed value is numeric
    """
    try:
        float(val)
        return True
    except ValueError:
        return False


def guess_type_from_name(name):
    """Make an educated guess about the type of a variable based on common naming conventions.

    Arguments:
        name {str} -- variable name

    Returns:
        {str} -- string of the builtin type or None if one cannot be found
    """
    if re.match("(?:is|has)[A-Z_]", name):
        return "bool"

    if re.match("^(?:cb|callback|done|next|fn)$", name):
        return "function"

    return None


def guess_type_from_value(value: Optional[str]) -> Optional[str]:
    """Make educated assertion about the type of the value.

    Arguments:
        value {str} -- string representation of a value

    Returns:
        {str} -- string of the builtin type or None if one cannot be found
    """
    if value is None or not isinstance(value, str):
        return None

    first_char = value[0:1]

    if is_numeric(value):
        return "number"

    char_map = {'"': "str", "'": "str", "[": "list", "{": "dict", "(": "tuple"}

    if char_map.get(first_char) is not None:
        return char_map.get(first_char)

    if value in ["True", "False"]:
        return "bool"

    if value[:2] in ["r'", 'r"', "R'", 'R"']:
        return "regexp"

    if value[:2] in ["u'", 'u"', "U'", 'U"']:
        return "unicode"

    if value[:7] == "lambda ":
        return "function"

    return None


MULTILINE_PATTERNS = (
    # A function defined on multiple lines
    re.compile(r"^\s*(async\s+)?def\s+\w+\($"),
    # An import statement takes up multiple lines
    re.compile(r"^from\s+\w+(\.\w+)*\s+import\s+\($"),
    # A variable defined on multiple lines
    re.compile(r"^\w+\s+=\s+\w+\($"),
)


def use_multiple_lines(line: str) -> bool:
    """Determines whether the current line uses a multi-line declaration or definition.

    Arguments:
        line (str) -- Definition Line

    Returns:
        bool -- Returns true if line uses a multi-line definition, otherwise returns false
    """
    line = line.strip()

    for ptn in MULTILINE_PATTERNS:
        if ptn.match(line):
            return True

    return False


class PythonParser:
    """Parser class Specific to Python.

    Contains the relevant parsing configuration to be able to handle Python style
    source files.
    """

    def __init__(self, view_settings: Optional[sublime.Settings] = None):
        """---."""
        self.view_settings = view_settings
        self.closing_string = '"""'

    @classmethod
    def get_definition(cls, view: sublime.View, position: int):
        """Get the definition line.

        String representation fo the line above the docstring

        Arguments:
            view {sublime.View} -- The sublime view in which this is executing
            position {Integer} -- Position of the docstring

        Decorators:
            classmethod

        Returns:
            {String} Representation of the definition line
        """
        # reset the position to the beginning of the line
        position = view.line(position).begin()

        log.debug("current position -> %s", position)

        # At beginning of the module
        if position == 0:
            return None, None

        # indentation_level = view.indentation_level(position)
        line: str = ""

        multiline = 0
        for current_line in read_next_line(view, position, True):
            current_line_string = view.substr(current_line).strip()
            line = current_line_string + " " + line
            multiline += 1

        log.debug("number of lines defined -> %s", multiline)
        log.debug("definition -- {}".format(line))

        return line, multiline

    @classmethod
    def read_above(
        cls, view: sublime.View, position: int, multiline: Optional[int] = None
    ):
        """Read the contents above the current definition line.
        Gathers additional context about the lines above a definition line,
        e.g. Decorators.
        Arguments:
            view {sublime.View} -- The sublime view in which this is executing
            position {Integer} -- Position of the docstring
        Returns:
            string, string -- type of definition, stringified definition contents
        """
        indentation_level = view.indentation_level(position)
        docstring_type = None
        definition = ""

        for current_line in read_next_line(view, position, True):
            # Not an empty line
            current_line_string = view.substr(current_line).strip()
            if len(current_line_string) == 0:
                continue

            # Ignore comments
            if re.match(r"^\s*(\#)", current_line_string):
                continue

            if multiline and multiline == 1:
                # When we move up in scope, stop reading
                current_indentation = view.indentation_level(current_line.end())
                if not current_indentation == indentation_level - 1:
                    break

                # Keeping it simple, will not parse multiline decorators
                if docstring_type is not None and not re.match(
                    r"^\s*(\@)", current_line_string
                ):
                    break

            # Set to module, class, or function
            if docstring_type is None:
                if re.match(r"^\s*(class )", current_line_string):
                    docstring_type = "class"
                elif re.match(r"^\s*(async\s+)?(def )", current_line_string):
                    docstring_type = "function"
                else:
                    docstring_type = "module"

            definition = current_line_string + "\n" + definition

        log.debug(
            "result of `read_above` -> type: '%s', definition: '%s'",
            docstring_type,
            definition,
        )

        return docstring_type, definition

    @classmethod
    def get_definition_contents(
        cls, view: sublime.View, position: int, multiline: Optional[int]
    ):
        """Get the relevant contents of the module/class/function.

        For Modules and Classes, will only provide the lines on the same
        indentation level as the docstring, so that the interpreter is only looking
        at what is possibly relevant. For functions, the whole content of the function
        if returned, since we will be looking for return/yield values, we cannot be
        certain won which indentation that will be made, if at all.

        Arguments:
            view {sublime.View} -- The sublime view in which this is executing
            position {Integer} -- Position the docstring was created on

        Decorators:
            classmethod

        Returns:
            {String} Contents that matter
        """
        indentation_level = view.indentation_level(position)
        definition: str = ""

        docstring_type, definition = cls.read_above(view, position, multiline)
        # Read above the docstring for function/class definition and decorators

        # Read the class/function contents
        for current_line in read_next_line(view, position):
            # Not an empty line
            current_line_string = view.substr(current_line).rstrip()
            if len(current_line_string) == 0:
                continue

            # Remove comments
            if re.match(r"^\s*(\#)", current_line_string):
                continue

            current_indentation = view.indentation_level(current_line.end())

            # Exit if this has de-indented below the current level
            if current_indentation < indentation_level:
                break

            # If this is a module or a class, we only care about the lines on
            # the same indentation level for contextual reasons
            if (
                not docstring_type == "function"
                and not current_indentation == indentation_level
            ):
                continue

            log.debug("contents each line: '%s'", current_line_string)

            # If it is a function defined on multiple lines,
            # the definitions should be combined into one line
            if use_multiple_lines(current_line_string):
                definition += current_line_string
            else:
                definition += current_line_string + "\n"

        return definition

    def parse(self, line: str, contents: str):
        """Central command to parse the areas above and below the docstring.

        Tries to determine which type of docstring should be created based upon
        whether the parser returns any output

        Arguments:
            line {String} -- Definition Line
            contents {String} -- Contents of the module/class/function

        Returns:
            {Dictionary} Store of attributes and their values
        """

        log.debug("line -> %s, contents: %s", line, contents)

        # At beginning of the module
        output = self.process_module(line, contents)
        if output is not None:
            return output

        output = self.process_class(line, contents)
        if output is not None:
            return output

        output = self.process_function(line, contents)
        if output is not None:
            return output

        return {}

    def process_variable(self, variable: str, hints: Optional[Dict[str, str]] = None):
        """Process an individual variable.

        Determines programmatically what the assumed type of the variable is,
        based on the initial assignment, or common naming conventions of the variable

        Arguments:
            variable {String} -- varibale definition line

        Keyword Arguments:
            hints {dict} -- dictionary to store typehints about the vars (default: None)

        Returns:
            {Dictionary} -- Dictionary of attributes to create snippets from
        """
        if not hints:
            hints = {}

        # params = {'name': None, 'type': None, 'default': None}
        params: Dict[str, Optional[str]] = {}

        if "=" in variable:
            pieces = variable.split("=")
            variable = pieces[0].strip()
            params["default"] = pieces[1].strip()

        if 0 < variable.find(":") < len(variable) - 1:
            pieces = variable.split(":", 2)
            variable = pieces[0].strip()
            hints[variable] = pieces[1].strip()

        if params.get("default") and hints.get(variable):
            if re.match(r"^Optional\[.+?\]$", hints[variable]):
                hints[variable] = re.sub(r"^Optional\[(.+?)\]$", r"\1", hints[variable])

        params["name"] = variable
        params["type"] = (
            hints.get(variable, "")
            or guess_type_from_value(params.get("default"))
            or guess_type_from_name(variable)
        )

        return params

    def parse_variables(self, contents: str):
        """Parse module level variables.

        Arguments:
            contents {String} -- Module Body

        Returns:
            {Dictionary} -- Dictionary of attributes to create snippets from
        """
        variables = []
        regex = re.compile(
            r"^\s*((?:(?!from |import |async |def |class |@).)+$)", re.MULTILINE
        )
        matches = re.findall(regex, contents)

        if len(matches) == 0:
            return None

        log.debug("class variables: %s", matches)

        for match in matches:
            variable = self.process_variable(match)
            variables.append(variable)

        return variables

    def process_module(self, line: str, contents: str):
        """Parse the whole module file to find module level variables.

        Reads the lines in the module contents to get the names of the module level variables.
        Arguments:
            contents {String} -- Module Body

        Decorators:
            classmethod

        Returns:
            {Dictionary} Dictionary of attributes to create snippets from
        """
        if line is not None:
            return None

        parsed_module = []
        variables = self.parse_variables(contents)

        if variables is not None:
            parsed_module.append(("attributes", variables))

        log.debug("module -> %s", parsed_module)

        return parsed_module

    def parse_extends(self, line):
        """Parse a class line to determine the extended classes.

        Arguments:
            line {string} -- Line containing the class definition

        Returns:
            {Dictionary} -- Dictionary of attributes to create snippets from
        """
        extends = re.search(r"^\s*class \w*\((.*)\):\s*$", line)

        if not extends:
            return None

        extends = split_by_commas(extends.group(1))
        parsed_extends = []
        for extend in extends:
            if extend == "object":
                continue

            parsed_extends.append(extend)

        return parsed_extends

    def process_class(self, line, contents):
        """Parse a class line to determine its attributes.

        Reads the class line to determine what other classes it extends
        Arguments:
            line     {String} -- Line containing the class definition
            contents {String} -- Class Body

        Decorators:
            classmethod

        Returns:
            {Dictionary} Dictionary of attributes to create snippets from
        """
        if not re.match(r"^\s*(class )", line):
            return None

        parsed_class = []

        extends = self.parse_extends(line)
        if extends is not None:
            parsed_class.append(("extends", extends))

        variables = self.parse_variables(contents)
        if variables is not None:
            parsed_class.append(("attributes", variables))

        log.debug("class -- %s", parsed_class)

        return parsed_class

    def parse_decorators(self, definition, content):
        """Parse the lines above the definition for decorators.

        Finds and returns all the decorators over a function that aren't
        in the excluded list.

        Arguments:
            definition {str} -- definition line.
            content {str} -- Content definition

        Returns:
            {list} -- list of decorators
        """
        lines = content.split("\n")
        excluded_decorators = ["classmethod", "staticmethod", "property"]
        decorators = []

        for line in lines:
            if line == definition:
                break

            match = re.findall(r"^\s*@([a-zA-Z0-9_\.]*)(\(.*\)|$)", line)

            if len(match) == 0:
                continue

            decorator = match[0][0]
            if decorator in excluded_decorators:
                continue

            decorators.append(decorator)

        return decorators

    def parse_arguments(self, line: str):
        """Find and parses each argument and keyword argument.

        Arguments:
            line {str} -- definition line to be parsed

        Returns:
            {dict} -- Contains a list of arguments and a list of
                      keyword arguments in their respective keys.
        """
        parsed_arguments = {"arguments": [], "keyword_arguments": []}

        arguments = re.search(r"^\s*def\s+\w+\((.*)\)", line)

        log.debug("found arguments by re -- %r", arguments)

        # Parse type hints
        hints = dict(
            re.findall(r"(\w+)\s*:\s*([\w\.]+\[[^:]*\]|[\w\.]+)\s*", arguments.group(1))  # type: ignore
        )

        log.debug("hints: %s", hints)

        # Remove type hints
        arguments = re.sub(r":\s*([\w\.]+\[[^:]*\]|[\w\.]+)\s*", "", arguments.group(1))  # type: ignore

        if not arguments:
            return None

        excluded_parameters = ["self", "cls"]
        arguments = split_by_commas(arguments)

        log.debug("arguments: %s", arguments)

        for index, argument in enumerate(arguments):
            if index == 0 and argument in excluded_parameters:
                continue

            argument_type = "keyword_arguments" if "=" in argument else "arguments"

            if argument[0] == "*":
                argument = argument[1:]
                hints[argument] = f"Tuple[{hints[argument]}]"

            params = self.process_variable(argument, hints)
            parsed_arguments[argument_type].append(params)

        return parsed_arguments

    def parse_returns(self, contents: str):
        """Find the first instances of returning in the definition.

        Parses through the whole definition for occurrances of the keyword `return`,
        or `yield` and returns the first. Tries guess the type of the value.

        Arguments:
            contents {str} -- contents of the definition

        Returns:
            {tuple} -- type of return and a dict for the return value type
        """
        regex = re.compile(r"^\s*(return|yield) (\S+)", re.MULTILINE)
        match = re.findall(regex, contents)

        if len(match) == 0:
            return None

        hint = re.search(
            r"^\s*def\s+\w+\(.*\)\s*->\s*([\w\.]+\[[^:]*\]|[\w\.]+)\s*:",
            contents,
            flags=re.DOTALL,
        )
        if hint:
            hint = hint.group(1)
            log.debug(
                "return value(s) type declaration found in function definition -> %s",
                hint,
            )

        match = match[0]
        return_type = match[0] + "s"
        return_value_type = hint or guess_type_from_value(match[1])

        return (return_type, {"type": return_value_type})

    def parse_raises(self, contents):
        """Find instances of raised exceptions in the definition.

        Parses through the whole definition for occurrances of the keyword `raise`,
        and appends the following value to the list of exceptions to be returned.

        Arguments:
            contents {str} -- contents of the definition

        Returns:
            {list} -- list of exception types
        """
        regex = re.compile(r"^\s*(raise) (\w+)", re.MULTILINE)
        match = re.findall(regex, contents)

        if len(match) == 0:
            return None

        raises = []
        for exception in match:
            if exception[1] not in raises:
                raises.append(exception[1])

        return raises

    def process_function(self, line: str, contents: str):
        """Parse a function for its arguments.

        Reads the function line to parse out the args and kwargs.
        Arguments:
            line     {String} -- Line containing the function definition
            contents {String} -- Function body

        Decorators:
            classmethod

        Returns:
            {Dictionary} Parsed valued group by type
        """
        if not re.match(r"^\s*(def )", line):
            log.debug("not function type")
            return None

        parsed_function = []

        decorators = self.parse_decorators(line, contents)
        if len(decorators) > 0:
            parsed_function.append(("decorators", decorators))

        arguments = self.parse_arguments(line)
        if arguments is not None:
            parsed_function.append(("arguments", arguments))

        returns = self.parse_returns(contents)
        if returns is not None:
            parsed_function.append(returns)

        raises = self.parse_raises(contents)
        if raises is not None:
            parsed_function.append(("raises", raises))

        log.debug("function -- %s", parsed_function)

        return parsed_function

    def is_docstring_closed(self, view, position):
        """Check if the current docstring is supposed to be closed.

        Keep reading lines until we reach the end of the file, class, or function
        We will assume that if the indentation level is ever lower than present, and no
        closing docstring has been found yet, the component has ended and needs to be closed

        Arguments:
            view     {sublime.View} -- Current Sublime Text View
            position {Integer}      -- Position in the view where the docstring is

        Returns:
            {Bool} True if the docstring is confirmed closed
        """

        def set_closing_string(match):
            if match is not None:
                s = match.group(0).strip()[0:3]
                if s in ['"""', "'''"]:
                    self.closing_string = s
                else:
                    raise Exception(
                        "could not find closing string.  Match was: {}".format(match)
                    )

        indentation_level = view.indentation_level(position)

        # Check the current line first, and ignore if docstring is closed on this line
        line = view.substr(view.line(position))
        match = re.search(r'^\s*(""".*"""|\'\'\'.*\'\'\')\s*$', line)

        if match is not None:
            set_closing_string(match)
            return False

        for current_line in read_next_line(view, position):
            # Not an empty line
            current_line_string = view.substr(current_line).rstrip()
            if not len(current_line_string):
                continue

            # Not on a more indented line
            current_indentation = view.indentation_level(current_line.end())
            if current_indentation > indentation_level:
                continue

            # Still within the same indentation level
            if current_indentation < indentation_level:
                break

            # Line only contains whitespace and """
            match = re.search(r'^\s*("""|\'\'\')', current_line_string)
            if match is not None:
                set_closing_string(match)
                return True

        set_closing_string(re.search(r'^\s*("""|\'\'\')', line))
        return False


def get_parser(view: sublime.View) -> Optional[PythonParser]:
    """Return the class of the parser to use.

    Arguments:
        view {sublime.View} -- The sublime text view in which this is executing in

    Returns:
        {PythonParser} or None if the current file type isn't a python file
    """
    scope = view.scope_name(view.sel()[0].end())
    res = re.search(r"\bsource\.([a-z+\-]+)", scope)
    source_lang = res.group(1) if res else "js"
    view_settings = view.settings()

    if source_lang == "python":
        return PythonParser(view_settings)

    return None
