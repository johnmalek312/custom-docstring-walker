"""Main module for DocstringWalker loader for Llama Hub."""

import ast
import logging
import os
from typing import List

from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import Document

TYPES_TO_PROCESS = {ast.FunctionDef, ast.ClassDef}

log = logging.getLogger(__name__)


class DocstringWalker(BaseReader):
    """A loader for docstring extraction and building structured documents from them.
    Recursively walks a directory and extracts docstrings from each Python
    module - starting from the module itself, then classes, then functions.
    Builds a graph of dependencies between the extracted docstrings.
    """

    def load_data(
        self,
        code_dir: str,
        skip_initpy: bool = True,
        fail_on_malformed_files: bool = False,
    ) -> List[Document]:
        """
        Load data from the specified code directory.
        Additionally, after loading the data, build a dependency graph between the loaded documents.
        The graph is stored as an attribute of the class.


        Parameters
        ----------
        code_dir : str
            The directory path to the code files.
        skip_initpy : bool
            Whether to skip the __init__.py files. Defaults to True.
        fail_on_malformed_files : bool
            Whether to fail on malformed files. Defaults to False - in this case,
            the malformed files are skipped and a warning is logged.

        Returns:
        -------
        List[Document]
            A list of loaded documents.
        """
        return self.process_directory(code_dir, skip_initpy, fail_on_malformed_files)

    def process_directory(
        self,
        code_dir: str,
        skip_initpy: bool = True,
        fail_on_malformed_files: bool = False,
    ) -> List[Document]:
        """
        Process a directory and extract information from Python files.
        Parameters
        ----------
        code_dir : str
            The directory path to the code files.
        skip_initpy : bool
            Whether to skip the __init__.py files. Defaults to True.
        fail_on_malformed_files : bool
            Whether to fail on malformed files. Defaults to False - in this case,
            the malformed files are skipped and a warning is logged.
    
        Returns:
        -------
        List[Document]
            A list of Document objects.
        """
        llama_docs = []
        for root, _, files in os.walk(code_dir):
            for file in files:
                if file.endswith(".py"):
                    if skip_initpy and file == "__init__.py":
                        continue
                    module_name = file.replace(".py", "")
                    module_path = os.path.join(root, file)
                    try:
                        doc = self.parse_module(module_name, module_path)
                        if doc:  # Only add if not None
                            llama_docs.append(doc)
                    except Exception as e:
                        if fail_on_malformed_files:
                            raise e  # noqa: TRY201
                        log.warning(
                            "Failed to parse file %s. Skipping. Error: %s",
                            module_path,
                            e,
                        )
        return llama_docs
    
    
    def read_module_text(self, path: str) -> str:
        """Read the text of a Python module. For tests this function can be mocked.

        Parameters
        ----------
        path : str
            Path to the module.

        Returns:
        -------
        str
            The text of the module.
        """
        with open(path, encoding="utf-8") as f:
            return f.read()
    
    def parse_module(self, module_name: str, path: str) -> Document:
        """Function for parsing a single Python module.

        Parameters
        ----------
        module_name : str
            A module name.
        path : str
            Path to the module.

        Returns:
        -------
        Document
            A LLama Index Document object with extracted information from the module.
        """
        module_text = self.read_module_text(path)
        module = ast.parse(module_text)
        has_register_tool_function = self.module_has_decorator_factory(module, "register_tool")
        
        if not has_register_tool_function:
            return None  # Skip this module
        module_docstring = ast.get_docstring(module)
        module_text = f"Module: {module_name} \n"
        if module_docstring:
            module_text += f"Docstring: {module_docstring} \n"
        sub_texts = []
        for elem in module.body:
            if type(elem) in TYPES_TO_PROCESS:
                sub_text = self.process_elem(elem, module_name)
                if sub_text:
                    sub_texts.append(sub_text)
        module_text += "\n".join(sub_texts)
        file_name = os.path.basename(path)
        return Document(text=module_text, metadata={"file_name": file_name})


    def process_class(self, class_node: ast.ClassDef, parent_node: str):
        """
        Process a class node in the AST and add relevant information to the graph.

        Parameters:
        ----------
        class_node : ast.ClassDef
            The class node to process. It represents a class definition
            in the abstract syntax tree (AST).
        parent_node : str
            The name of the parent node. It specifies the name of the parent node in the graph.

        Returns:
        ----------
        str
            A string representation of the processed class node and its sub-elements.
            It provides a textual representation of the processed class node and its sub-elements.
        """
        sub_texts = []  
        for elem in class_node.body:
            result = self.process_elem(elem, class_node.name)
            if result:
                sub_texts.append(result)
        return "\n".join(sub_texts)

    def process_function(self, func_node: ast.FunctionDef, parent_node: str) -> str:
        """
        Process a function node in the AST and add it to the graph. Build node text.

        Parameters
        ----------
        func_node : ast.FunctionDef
            The function node to process.
        parent_node : str
            The name of the parent node.

        Returns:
        -------
        str
            A string representation of the processed function node with its sub-elements.
        """
        if self.has_decorator_factory(func_node, "register_tool"):  # Check for decorator
            func_name = func_node.name
            func_docstring = ast.get_docstring(func_node) or ""
            text = f"\nFunction: {func_name}\n{func_docstring}"
            return text  # Only return the function docstring, no sub-elements

    def process_elem(self, elem, parent_node: str) -> str:
        """
        Process an element in the abstract syntax tree (AST).

        This is a generic function that delegates the execution to more specific
        functions based on the type of the element.

        Args:
            elem (ast.AST): The element to process.
            parent_node (str): The parent node in the graph.
            graph (nx.Graph): The graph to update.

        Returns:
            str: The result of processing the element.
        """
        if isinstance(elem, ast.FunctionDef):
            return self.process_function(elem, parent_node)
        elif isinstance(elem, ast.ClassDef):
            return self.process_class(elem, parent_node)
        return ""

    def has_decorator_factory(self, func_node: ast.FunctionDef, decorator_factory: str) -> bool:
        """Check if a function has the @register_tool() decorator."""
        for decorator in func_node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                if decorator.func.id == decorator_factory:
                    return True
        return False

    def module_has_decorator_factory(self, module: ast.Module | ast.ClassDef, decorator_factory: str) -> bool:
        """Check if a module or class has a function that has the @register_tool() decorator."""
        for element in module.body:
            if isinstance(element, ast.ClassDef) and self.module_has_decorator_factory(element, decorator_factory):
                return True
            elif isinstance(element, ast.FunctionDef) and self.has_decorator_factory(element, decorator_factory):
                return True
        return False
