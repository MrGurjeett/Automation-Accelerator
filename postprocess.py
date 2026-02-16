import re
import json
import ast
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from urllib.parse import urlparse


class PostProcessCodegen:
    CONFIG_PATH = Path(__file__).with_name("postprocess_config.json")

    # ==========================================================
    # INIT / CONFIG
    # ==========================================================
    def __init__(self):
        self.config = self._load_config()

    def _load_config(self):
        defaults = {
            "login_step_text": "the user is on the login page",
            "login_url": "https://intc.ntrs.com/idm/ng-web",
        }
        if not self.CONFIG_PATH.exists():
            return defaults
        try:
            data = json.loads(self.CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return defaults
            merged = defaults.copy()
            merged.update({k: v for k, v in data.items() if isinstance(k, str)})
            return merged
        except Exception:
            return defaults

    # ==========================================================
    # UI HELPERS
    # ==========================================================
    def ask_file(self, prompt, ext, filetypes):
        root = tk.Tk()
        root.withdraw()
        choice = messagebox.askquestion(prompt, "Use existing file? (No = create new)")
        if choice == "yes":
            file = filedialog.askopenfilename(defaultextension=ext, filetypes=filetypes)
        else:
            file = filedialog.asksaveasfilename(defaultextension=ext, filetypes=filetypes)
        root.destroy()
        return file

    def ask_dir(self, prompt):
        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(title=prompt)
        root.destroy()
        return folder

    # ==========================================================
    # UTILS
    # ==========================================================
    def _safe_name(self, val):
        return re.sub(r"[^a-zA-Z0-9_]", "_", str(val)).lower()

    def _normalize_step_text(self, step_text):
        return re.sub(r"^(Given|When|Then)\s+", "", step_text).strip()

    def _normalize_assertion_line(self, line):
        if not line:
            return line
        if line.startswith("expect("):
            line = line.replace("expect(page", "expect(self.page", 1)
        if "page." in line and "self.page." not in line:
            line = line.replace("page.", "self.page.")
        return line

    def _is_expect_call(self, node):
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "expect"
        )

    # ==========================================================
    # ACTION MAP
    # ==========================================================
    ACTION_MAP = {
        "click": "When the user clicks on {selector}",
        "fill": "When the user enters '{value}' in {selector}",
        "type": "When the user types '{value}' in {selector}",
        "press": "When the user presses '{key}' in {selector}",
        "get_by_text_click": "When the user clicks on text {value}",
        "get_by_text_nth_click": "When the user clicks on {index}th text {value}",
        "get_by_role_click": "When the user clicks on role {role} named {name}",
        "get_by_role_first_click": "When the user clicks on first role {role} named {name}",
        "get_by_role_nth_click": "When the user clicks on {index}th role {role} named {name}",
        "check": "When the user checks the checkbox {name}",
        "check_role": "When the user checks the role {role} named {name}",
        "uncheck": "When the user unchecks the checkbox {name}",
        "uncheck_role": "When the user unchecks the role {role} named {name}",
        "goto": "Given the user navigates to {url}",
        "close": "When the user closes the page",
    }

    # ==========================================================
    # AST → STEPS
    # ==========================================================
    def extract_steps_from_codegen(self, codegen_path):
        with open(codegen_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=codegen_path)

        steps = []

        for node in ast.walk(tree):

            if (
                isinstance(node, ast.Call)
                and hasattr(node.func, "attr")
                and hasattr(node.func.value, "id")
                and node.func.value.id == "page"
                and node.func.attr == "goto"
            ):
                url = ast.literal_eval(node.args[0])
                steps.append({"action": "goto", "url": url})

            if (
                isinstance(node, ast.Call)
                and hasattr(node.func, "attr")
                and isinstance(node.func.value, ast.Call)
                and hasattr(node.func.value.func, "attr")
                and node.func.value.func.attr == "locator"
            ):
                selector = ast.literal_eval(node.func.value.args[0])

                if node.func.attr == "click":
                    steps.append({"action": "click", "selector": selector})

                elif node.func.attr in ("fill", "type") and node.args:
                    value = ast.literal_eval(node.args[0])
                    steps.append(
                        {
                            "action": node.func.attr,
                            "selector": selector,
                            "value": value,
                        }
                    )

                elif node.func.attr == "press" and node.args:
                    key = ast.literal_eval(node.args[0])
                    steps.append(
                        {
                            "action": "press",
                            "selector": selector,
                            "key": key,
                        }
                    )

            if self._is_expect_call(node):
                assertion = self._normalize_assertion_line(ast.unparse(node))
                if steps:
                    steps[-1].setdefault("assertions", []).append(assertion)

            if (
                isinstance(node, ast.Call)
                and hasattr(node.func, "attr")
                and hasattr(node.func.value, "id")
                and node.func.value.id == "page"
                and node.func.attr == "close"
            ):
                steps.append({"action": "close"})

        return steps

    # ==========================================================
    # FEATURE FILE
    # ==========================================================
    def generate_feature_file(self, steps, feature_path, scenario_name):
        lines = [
            "Feature: Generated from Playwright codegen",
            "",
            f"  Scenario: {scenario_name}",
        ]

        for step in steps:
            template = self.ACTION_MAP.get(step["action"])
            if template:
                lines.append("    " + template.format(**step))

        with open(feature_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # ==========================================================
    # STEP DEFINITIONS FILE
    # ==========================================================
    def generate_step_definitions_file(self, steps, steps_file):
        """Generate step definitions file from extracted steps"""
        lines = [
            '"""',
            'Generated Step Definitions',
            '"""',
            'from pytest_bdd import given, when, parsers',
            'import logging',
            '',
            'logger = logging.getLogger(__name__)',
            '',
        ]

        seen_patterns = set()

        for step in steps:
            action = step.get("action")
            template = self.ACTION_MAP.get(action)
            if not template:
                continue

            raw_text = template.format(**step)
            step_text = self._normalize_step_text(raw_text)

            if step_text in seen_patterns:
                continue
            seen_patterns.add(step_text)

            decorator = "@when('{step}')".format(step=step_text)
            if action == "goto":
                decorator = "@given('{step}')".format(step=step_text)

            if "{" in step_text and "}" in step_text:
                decorator = decorator.replace("@when('", "@when(parsers.parse(\"")
                decorator = decorator.replace("@given('", "@given(parsers.parse(\"")
                decorator = decorator.replace("')", "\"))")

            func_name = f"step_{self._safe_name(step_text)}"
            lines.extend([
                '',
                decorator,
                f"def {func_name}(page, **kwargs):",
                "    # TODO: Implement step using page objects or locators",
                "    logger.info('Executed step: ' + '" + step_text + "')",
            ])

        with open(steps_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # ==========================================================
    # PAGE / STEP GROUPING
    # ==========================================================
    def build_pages_and_steps(self, steps):
        pages = []
        annotated = []
        current_page = None
        current_url = None
        page_index = 0

        for step in steps:
            step = dict(step)
            if step.get("action") == "goto":
                url = step["url"]
                if current_url != url:
                    page_index += 1
                    parsed = urlparse(url)
                    name = parsed.path.strip("/").split("/")[-1] or parsed.netloc
                    class_name = f"{name.title().replace('-', '').replace('_', '')}Page"
                    module_name = f"{self._safe_name(class_name)}"
                    current_page = {
                        "index": page_index,
                        "url": url,
                        "class_name": class_name,
                        "module_name": module_name,
                    }
                    pages.append(current_page)
                    current_url = url

            if not current_page:
                page_index += 1
                current_page = {
                    "index": page_index,
                    "url": None,
                    "class_name": f"Page{page_index}",
                    "module_name": f"page_{page_index}",
                }
                pages.append(current_page)

            step["page"] = current_page
            annotated.append(step)

        return pages, annotated

    # ==========================================================
    # PAGE OBJECT METHODS
    # ==========================================================
    def build_page_action(self, step):
        action = step.get("action")
        selector = step.get("selector")
        value = step.get("value")
        key = step.get("key")
        role = step.get("role")
        name = step.get("name")
        index = step.get("index")
        assertions = step.get("assertions", [])

        selector_safe = self._safe_name(selector) if selector else None
        locators = {}
        body_lines = []
        method_args = []
        method_name = None

        if action == "click" and selector:
            loc = selector_safe.upper()
            locators[loc] = selector
            method_name = f"click_{selector_safe}"
            body_lines.append(f"self.page.click(self.{loc})")

        elif action in ("fill", "type") and selector:
            loc = selector_safe.upper()
            locators[loc] = selector
            method_name = f"{action}_in_{selector_safe}"
            method_args = ["value"]
            body_lines.append(f"self.page.{action}(self.{loc}, value)")

        elif action == "close":
            method_name = "close_page"
            body_lines.append("self.page.close()")

        for assertion in assertions:
            body_lines.append(self._normalize_assertion_line(assertion))

        if not method_name:
            return None

        args_sig = ", ".join(["self"] + method_args)
        lines = [f"def {method_name}({args_sig}):"]
        for l in body_lines:
            lines.append(f"    {l}")

        return {
            "method_name": method_name,
            "method_args": method_args,
            "locators": locators,
            "method_lines": lines,
            "has_assertions": bool(assertions),
        }

    def prepare_page_definitions(self, steps):
        pages, annotated = self.build_pages_and_steps(steps)
        page_defs = {}

        for step in annotated:
            page = step["page"]
            key = page["class_name"]
            page_defs.setdefault(
                key,
                {
                    "class_name": page["class_name"],
                    "module_name": page["module_name"],
                    "url": page.get("url"),
                    "locators": {},
                    "methods": {},
                },
            )

            step["page_class"] = page_defs[key]["class_name"]
            step["page_module"] = page_defs[key]["module_name"]

            action_info = self.build_page_action(step)
            if not action_info:
                continue

            for loc_key, loc_val in action_info["locators"].items():
                unique_key = loc_key
                suffix = 1
                while unique_key in page_defs[key]["locators"] and page_defs[key]["locators"][unique_key] != loc_val:
                    unique_key = f"{loc_key}_{suffix}"
                    suffix += 1
                page_defs[key]["locators"][unique_key] = loc_val
                if unique_key != loc_key:
                    action_info["method_lines"] = [
                        line.replace(f"self.{loc_key}", f"self.{unique_key}")
                        for line in action_info["method_lines"]
                    ]

            method_key = action_info["method_name"]
            suffix = 1
            while method_key in page_defs[key]["methods"]:
                method_key = f"{action_info['method_name']}_{suffix}"
                suffix += 1

            action_info["method_name"] = method_key
            page_defs[key]["methods"][method_key] = action_info

            step["method_name"] = method_key

        return page_defs, annotated

    # ==========================================================
    # PAGE OBJECT FILES
    # ==========================================================
    def generate_page_class_files(self, steps, pages_dir):
        page_defs, _ = self.prepare_page_definitions(steps)
        pages_dir = Path(pages_dir)
        pages_dir.mkdir(parents=True, exist_ok=True)

        for data in page_defs.values():
            path = pages_dir / f"{data['module_name']}.py"
            lines = [
                "from playwright.sync_api import Page, expect",
                "",
                f"class {data['class_name']}:",
                "    def __init__(self, page: Page):",
                "        self.page = page",
                "",
            ]

            if data.get("url"):
                lines.extend([
                    f"    URL = {data['url']!r}",
                    "",
                    "    def open(self):",
                    "        self.page.goto(self.URL)",
                    "        self.page.wait_for_load_state('domcontentloaded')",
                    "",
                ])

            for loc, val in data["locators"].items():
                lines.append(f"    {loc} = {val!r}")

            lines.append("")

            for method in data["methods"].values():
                for line in method["method_lines"]:
                    lines.append("    " + line)
                lines.append("")

            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ==========================================================
    # STEP DEFINITIONS FILE
    # ==========================================================
    def generate_step_definitions_file(self, steps, steps_file, pages_dir):
        """Generate step definitions file from extracted steps"""
        import os

        page_defs, annotated = self.prepare_page_definitions(steps)

        steps_file = Path(steps_file).resolve()
        pages_dir = Path(pages_dir).resolve()
        steps_parent = steps_file.parent
        rel_pages = os.path.relpath(pages_dir, steps_parent)

        lines = [
            '"""',
            'Generated Step Definitions',
            '"""',
            'from pathlib import Path',
            'import sys',
            'from pytest_bdd import given, when, parsers',
            'import logging',
            '',
            f"PAGES_DIR = (Path(__file__).resolve().parent / r'{rel_pages}').resolve()",
            'if str(PAGES_DIR) not in sys.path:',
            '    sys.path.append(str(PAGES_DIR))',
            '',
        ]

        for data in page_defs.values():
            lines.append(f"from {data['module_name']} import {data['class_name']}")

        lines.extend([
            '',
            'logger = logging.getLogger(__name__)',
            '',
        ])

        seen_patterns = set()

        for index, step in enumerate(annotated, start=1):
            action = step.get("action")
            page_class = step.get("page_class")
            method_name = step.get("method_name")

            template = self.ACTION_MAP.get(action)
            if not template:
                continue

            raw_text = template.format(**step)
            step_text = self._normalize_step_text(raw_text)

            if step_text in seen_patterns:
                continue
            seen_patterns.add(step_text)

            decorator = "@when('{step}')".format(step=step_text)
            if action == "goto":
                decorator = "@given('{step}')".format(step=step_text)

            arg_names = re.findall(r"{(\w+)}", step_text)
            signature_args = ", ".join(["page"] + arg_names)

            if arg_names:
                decorator = decorator.replace("@when('", "@when(parsers.parse(\"")
                decorator = decorator.replace("@given('", "@given(parsers.parse(\"")
                decorator = decorator.replace("')", "\"))")

            func_name = f"step_{index:03d}_{self._safe_name(step_text)}"

            if action in ("fill", "type"):
                method_call = f"    {page_class}(page).{method_name}(value)"
            elif action == "press":
                method_call = f"    {page_class}(page).{method_name}(key)"
            else:
                method_call = f"    {page_class}(page).{method_name}()"

            lines.extend([
                '',
                decorator,
                f"def {func_name}({signature_args}):",
                method_call,
                "    logger.info('Executed step')",
            ])

        with open(steps_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


# ==========================================================
# CLI ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert Playwright codegen output to BDD steps, feature files, and page objects."
    )
    parser.add_argument("--codegen", required=True, help="Path to codegen output")
    parser.add_argument("--scenario", required=True, help="Scenario name")
    args = parser.parse_args()

    processor = PostProcessCodegen()

    feature_file = processor.ask_file(
        "Feature File", ".feature", [("Feature Files", "*.feature")]
    )
    steps_file = processor.ask_file(
        "Steps File", ".py", [("Python Files", "*.py")]
    )

    steps = processor.extract_steps_from_codegen(args.codegen)
    processor.generate_feature_file(steps, feature_file, args.scenario)

    pages_dir = processor.ask_dir("Select Pages Folder")
    processor.generate_page_class_files(steps, pages_dir)
    processor.generate_step_definitions_file(steps, steps_file, pages_dir)

    print(
        f"BDD scenario, step definitions, and page classes written to {feature_file}, {steps_file}, and {pages_dir}"
    )