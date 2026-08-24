import re
from typing import Dict, Any

class SemanticCompiler:
    """
    Parses raw terminal command logs and extracts reusable parameter templates 
    and default variable mappings for skill library storage.
    """

    def compile_command(self, raw_command: str, action_type: str = "TERMINAL_EXEC") -> Dict[str, Any]:
        default_parameters = {}
        parameterized_script = raw_command
        var_counter = 1

        # 1. Parameterize ports (e.g. --port=3000, -p 3000)
        port_matches = re.finditer(r'(--port=|-p\s+|=)(\d{2,5})', raw_command)
        for match in port_matches:
            prefix, port = match.group(1), match.group(2)
            var_name = f"PORT_NUMBER_{var_counter}"
            var_counter += 1
            default_parameters[var_name] = port
            target = f"{prefix}{port}"
            replacement = f"{prefix}${{{var_name}}}"
            parameterized_script = parameterized_script.replace(target, replacement)

        # 2. Parameterize directory paths (e.g. D:/Projects/auth-service, /var/log, ./dir)
        path_matches = re.finditer(r'([A-Za-z]:[/\\][^\s]+|/(?:[^\s]+)|(?:\./)[^\s]+)', parameterized_script)
        for match in path_matches:
            path = match.group(1)
            var_name = f"PROJECT_PATH_{var_counter}"
            var_counter += 1
            default_parameters[var_name] = path
            parameterized_script = parameterized_script.replace(path, f"${{{var_name}}}")

        return {
            "raw_command": raw_command,
            "parameterized_script": parameterized_script,
            "default_parameters": default_parameters,
            "action_type": action_type
        }
