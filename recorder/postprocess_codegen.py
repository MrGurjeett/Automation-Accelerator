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
            "login_url": "https://www.demoblaze.com/",
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

    def ask_feature_file(self, prompt, ext, filetypes):
        root = tk.Tk()
        root.withdraw()
        choice = messagebox.askyesnocancel(
            prompt, "Use existing file? (No = create new, Cancel = Abort)"
        )
        if choice is None:
            root.destroy()
            return None
        if choice is True:
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

    def _humanize_token(self, text):
        if not text:
            return ""
        text = re.sub(r"\.[A-Za-z]", lambda m: " " + m.group(0)[1:], text)
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        text = re.sub(r"[-_]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.title()

    def _infer_element_name(self, selector):
        if not selector:
            return "Element"

        patterns = [
            r"\[id=\"([^\"]+)\"\]",
            r"\[name=\"([^\"]+)\"\]",
            r"\[data-test=\"([^\"]+)\"\]",
            r"\[data-testid=\"([^\"]+)\"\]",
            r"\[aria-label=\"([^\"]+)\"\]",
            r"\[placeholder=\"([^\"]+)\"\]",
        ]

        for pattern in patterns:
            match = re.search(pattern, selector)
            if match:
                return self._humanize_token(match.group(1))

        if selector.startswith("#"):
            return self._humanize_token(selector[1:])

        return self._humanize_token(selector)

    def _infer_page_name(self, url):
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        name = path.split("/")[-1] if path else parsed.netloc
        name = re.sub(r"\.(html|htm|php|aspx|jsp)$", "", name, flags=re.IGNORECASE)
        name = name or "Home"
        return self._humanize_token(name)

    def _infer_element_name_from_step(self, step):
        if step.get("selector"):
            return self._infer_element_name(step.get("selector"))
        if step.get("text"):
            return self._humanize_token(step.get("text"))
        if step.get("label"):
            return self._humanize_token(step.get("label"))
        if step.get("placeholder"):
            return self._humanize_token(step.get("placeholder"))
        if step.get("title"):
            return self._humanize_token(step.get("title"))
        if step.get("alt_text"):
            return self._humanize_token(step.get("alt_text"))
        if step.get("role"):
            role = self._humanize_token(step.get("role"))
            name = self._humanize_token(step.get("name")) if step.get("name") else ""
            return f"{name} {role}".strip()
        return "Element"

    def _escape_single_quotes(self, text):
        return text.replace("'", "\\'") if text else text

    def _escape_double_quotes(self, text):
        return text.replace('"', '\\"') if text else text

    def _format_value_for_feature(self, value):
        if isinstance(value, (dict, list, tuple)):
            try:
                return json.dumps(value)
            except Exception:
                return str(value)
        return value

    def _normalize_step_text(self, step_text):
        return re.sub(r"^(Given|When|Then)\s+", "", step_text).strip()

    def _should_force_click(self, selector):
        if not selector:
            return False
        lower = selector.lower()
        return (
            " svg" in lower
            or lower.endswith("svg")
            or " path" in lower
            or lower.endswith("path")
            or "rct-icon" in lower
        )

    def _should_use_first_locator(self, selector):
        if not selector:
            return False
        lower = selector.lower()
        if lower.startswith("//") or lower.startswith("xpath="):
            return False
        unique_markers = ["#", "[id=", "data-testid", "data-test", "aria-label", "placeholder", "name="]
        if any(marker in lower for marker in unique_markers):
            return False
        return True

    def _should_guard_click(self, selector):
        if not selector:
            return False
        return "rct-icon" in selector.lower()

    def _normalize_assertion_line(self, line, target="self.page"):
        if not line:
            return line
        if line.startswith("expect("):
            line = line.replace("expect(page", f"expect({target}", 1)
        if target == "self.page":
            if "page." in line and "self.page." not in line:
                line = line.replace("page.", "self.page.")
        else:
            if "self.page." in line:
                line = line.replace("self.page.", "page.")
        return line

    def _is_expect_call(self, node):
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "expect"
        )

    def _iter_nodes_in_order(self, node):
        yield node
        for _, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        yield from self._iter_nodes_in_order(item)
            elif isinstance(value, ast.AST):
                yield from self._iter_nodes_in_order(value)

    def _parse_locator_target(self, call):
        index = None
        if isinstance(call, ast.Attribute) and call.attr == "first":
            index = 0
            call = call.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "nth":
            if call.args:
                try:
                    index = ast.literal_eval(call.args[0])
                except Exception:
                    index = None
            call = call.func.value

        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
            return None

        if not (isinstance(call.func.value, ast.Name) and call.func.value.id == "page"):
            return None

        method = call.func.attr
        data = {"target": method, "index": index}

        try:
            if method == "locator":
                data["selector"] = ast.literal_eval(call.args[0])
            elif method == "get_by_text":
                data["text"] = ast.literal_eval(call.args[0])
                for kw in call.keywords or []:
                    if kw.arg == "exact":
                        data["exact"] = ast.literal_eval(kw.value)
            elif method == "get_by_role":
                data["role"] = ast.literal_eval(call.args[0]) if call.args else None
                for kw in call.keywords or []:
                    if kw.arg == "name":
                        data["name"] = ast.literal_eval(kw.value)
                    if kw.arg == "exact":
                        data["exact"] = ast.literal_eval(kw.value)
            elif method == "get_by_label":
                data["label"] = ast.literal_eval(call.args[0])
            elif method == "get_by_placeholder":
                data["placeholder"] = ast.literal_eval(call.args[0])
            elif method == "get_by_title":
                data["title"] = ast.literal_eval(call.args[0])
            elif method == "get_by_alt_text":
                data["alt_text"] = ast.literal_eval(call.args[0])
            else:
                return None
        except Exception:
            return None

        return data

    # ==========================================================
    # ACTION MAP
    # ==========================================================
    ACTION_MAP = {
        "goto": "Given the user is on the {page_name} page",
        "click": "When the user clicks {element_name}",
        "right_click": "When the user right clicks {element_name}",
        "dblclick": "When the user double clicks {element_name}",
        "hover": "When the user hovers over {element_name}",
        "fill": "When the user enters '{value}' into {element_name}",
        "type": "When the user types '{value}' into {element_name}",
        "press": "When the user presses '{key}' in {element_name}",
        "check": "When the user checks {element_name}",
        "uncheck": "When the user unchecks {element_name}",
        "select_option": "When the user selects '{value}' from {element_name}",
        "set_input_files": "When the user uploads '{file_path}' to {element_name}",
        "close": "When the user closes the page",
    }

    # ==========================================================
    # AST → STEPS
    # ==========================================================
    def extract_steps_from_codegen(self, codegen_path):
        with open(codegen_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=codegen_path)

        steps = []

        for node in self._iter_nodes_in_order(tree):

            if (
                isinstance(node, ast.Call)
                and hasattr(node.func, "attr")
                and hasattr(node.func.value, "id")
                and node.func.value.id == "page"
                and node.func.attr == "goto"
            ):
                url = ast.literal_eval(node.args[0])
                steps.append({"action": "goto", "url": url})

            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                action = node.func.attr
                if action in (
                    "click",
                    "dblclick",
                    "hover",
                    "check",
                    "uncheck",
                    "fill",
                    "type",
                    "press",
                    "select_option",
                    "set_input_files",
                ):
                    target = self._parse_locator_target(node.func.value)

                    remaining_args = list(node.args)
                    if target is None and isinstance(node.func.value, ast.Name) and node.func.value.id == "page":
                        try:
                            selector = ast.literal_eval(node.args[0])
                        except Exception:
                            selector = None
                        target = {"target": "locator", "selector": selector, "index": None}
                        remaining_args = list(node.args[1:])

                    if target:
                        step = {"action": action, **{k: v for k, v in target.items() if v is not None}}
                        if action == "click":
                            for kw in node.keywords or []:
                                if kw.arg == "button":
                                    try:
                                        step["button"] = ast.literal_eval(kw.value)
                                    except Exception:
                                        step["button"] = None
                            if step.get("button") == "right":
                                step["action"] = "right_click"

                        if action in ("fill", "type") and remaining_args:
                            step["value"] = ast.literal_eval(remaining_args[0])
                        elif action == "press" and remaining_args:
                            step["key"] = ast.literal_eval(remaining_args[0])
                        elif action == "select_option" and remaining_args:
                            try:
                                step["value"] = ast.literal_eval(remaining_args[0])
                            except Exception:
                                step["value"] = ast.unparse(remaining_args[0])
                        elif action == "set_input_files" and remaining_args:
                            step["file_path"] = ast.literal_eval(remaining_args[0])

                        steps.append(step)

            if self._is_expect_call(node):
                assertion = ast.unparse(node)
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
        scenario_lines = [
            f"  Scenario: {scenario_name}",
        ]

        for step in steps:
            template = self.ACTION_MAP.get(step["action"])
            if template:
                formatted = dict(step)
                if "value" in formatted:
                    formatted["value"] = self._format_value_for_feature(formatted["value"])
                if "file_path" in formatted:
                    formatted["file_path"] = self._format_value_for_feature(formatted["file_path"])
                scenario_lines.append("    " + template.format(**formatted))

        feature_file = Path(feature_path)
        feature_header = "Feature: Generated from Playwright codegen"

        existing_lines = []
        if feature_file.exists():
            existing_lines = feature_file.read_text(encoding="utf-8").splitlines()

        cleaned_lines = []
        header_written = False

        for line in existing_lines:
            if line.strip().startswith("Feature:"):
                if not header_written:
                    feature_header = line.rstrip()
                    cleaned_lines.append(feature_header)
                    header_written = True
                continue
            cleaned_lines.append(line)

        if not header_written:
            cleaned_lines = [feature_header] + (cleaned_lines if cleaned_lines else [])

        # Ensure a blank line after Feature header
        if len(cleaned_lines) == 1 or cleaned_lines[1].strip() != "":
            cleaned_lines.insert(1, "")

        # Remove existing scenario with the same name
        updated_lines = []
        skip_block = False
        for line in cleaned_lines:
            stripped = line.strip()
            if stripped.startswith("Scenario:"):
                current_name = stripped[len("Scenario:"):].strip()
                skip_block = current_name == scenario_name
                if skip_block:
                    continue
            if skip_block:
                continue
            updated_lines.append(line)

        while updated_lines and updated_lines[-1].strip() == "":
            updated_lines.pop()

        if updated_lines and updated_lines[-1].strip() != "":
            updated_lines.append("")

        updated_lines.extend(scenario_lines)

        feature_file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

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
                    page_name = self._infer_page_name(url)
                    name = page_name.replace(" ", "")
                    class_name = f"{name}Page"
                    module_name = f"{self._safe_name(class_name)}"
                    current_page = {
                        "index": page_index,
                        "url": url,
                        "page_name": page_name,
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
                    "page_name": f"Page {page_index}",
                    "class_name": f"Page{page_index}",
                    "module_name": f"page_{page_index}",
                }
                pages.append(current_page)

            step["page"] = current_page
            if step.get("action") == "goto":
                step["page_name"] = current_page.get("page_name")
            if step.get("action") not in ("goto",):
                step["element_name"] = self._infer_element_name_from_step(step)
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
        file_path = step.get("file_path")
        role = step.get("role")
        name = step.get("name")
        index = step.get("index")
        element_name = step.get("element_name")
        target = step.get("target")
        button = step.get("button")

        selector_safe = self._safe_name(element_name or selector or "element")
        locators = {}
        body_lines = []
        method_args = []
        method_name = None

        def build_target_call():
            if target == "get_by_text":
                exact = step.get("exact")
                exact_arg = f", exact={exact!r}" if exact is not None else ""
                base = f"self.page.get_by_text({step.get('text')!r}{exact_arg})"
            elif target == "get_by_role":
                name_arg = f", name={name!r}" if name is not None else ""
                exact = step.get("exact")
                exact_arg = f", exact={exact!r}" if exact is not None else ""
                if exact is None and role == "link" and isinstance(name, str) and name.strip() == "Cart":
                    exact_arg = ", exact=True"
                base = f"self.page.get_by_role({role!r}{name_arg}{exact_arg})"
            elif target == "get_by_label":
                base = f"self.page.get_by_label({step.get('label')!r})"
            elif target == "get_by_placeholder":
                base = f"self.page.get_by_placeholder({step.get('placeholder')!r})"
            elif target == "get_by_title":
                base = f"self.page.get_by_title({step.get('title')!r})"
            elif target == "get_by_alt_text":
                base = f"self.page.get_by_alt_text({step.get('alt_text')!r})"
            else:
                return None

            if role == "link" and isinstance(name, str) and name.strip().lower() == "delete":
                base = f"{base}.first"
            if index is not None:
                base = f"{base}.nth({index})"
            return base

        if action in ("click", "right_click", "dblclick", "hover", "check", "uncheck") and selector:
            loc = selector_safe.upper()
            locators[loc] = selector
            method_name = f"{action}_{selector_safe}"
            if target == "locator" or index is not None:
                base = f"self.page.locator(self.{loc})"
                if index == 0:
                    base = f"{base}.first"
                elif index is not None:
                    base = f"{base}.nth({index})"
                elif action == "click" and self._should_use_first_locator(selector):
                    base = f"{base}.first"
                force_click = action == "click" and self._should_force_click(selector)
                if action == "click" and self._should_guard_click(selector):
                    body_lines.append(f"if {base}.count() > 0:")
                    body_lines.append(f"    {base}.{action}(force=True)")
                else:
                    wait_state = "attached" if force_click else "visible"
                    body_lines.append(f"{base}.wait_for(state='{wait_state}')")
                    if action == "right_click":
                        body_lines.append(f"{base}.click(button='right')")
                    elif force_click:
                        body_lines.append(f"{base}.{action}(force=True)")
                    else:
                        body_lines.append(f"{base}.{action}()")
            else:
                if action == "right_click":
                    body_lines.append(f"self.page.click(self.{loc}, button='right')")
                elif action == "click" and self._should_force_click(selector):
                    body_lines.append(f"self.page.{action}(self.{loc}, force=True)")
                else:
                    body_lines.append(f"self.page.{action}(self.{loc})")

        elif action in ("click", "right_click", "dblclick", "hover", "check", "uncheck"):
            base = build_target_call()
            if base:
                method_name = f"{action}_{selector_safe}"
                if action == "right_click":
                    body_lines.append(f"{base}.click(button='right')")
                else:
                    body_lines.append(f"{base}.{action}()")

        elif action in ("fill", "type") and selector:
            loc = selector_safe.upper()
            locators[loc] = selector
            method_name = f"{action}_in_{selector_safe}"
            method_args = ["value"]
            body_lines.append(f"self.page.{action}(self.{loc}, value)")

        elif action in ("fill", "type"):
            base = build_target_call()
            if base:
                method_name = f"{action}_in_{selector_safe}"
                method_args = ["value"]
                body_lines.append(f"{base}.{action}(value)")

        elif action == "press" and selector:
            loc = selector_safe.upper()
            locators[loc] = selector
            method_name = f"press_in_{selector_safe}"
            method_args = ["key"]
            body_lines.append(f"self.page.press(self.{loc}, key)")

        elif action == "press":
            base = build_target_call()
            if base:
                method_name = f"press_in_{selector_safe}"
                method_args = ["key"]
                body_lines.append(f"{base}.press(key)")

        elif action == "select_option" and selector:
            loc = selector_safe.upper()
            locators[loc] = selector
            method_name = f"select_{selector_safe}"
            method_args = ["value"]
            body_lines.append(f"self.page.select_option(self.{loc}, value)")

        elif action == "select_option":
            base = build_target_call()
            if base:
                method_name = f"select_{selector_safe}"
                method_args = ["value"]
                body_lines.append(f"{base}.select_option(value)")

        elif action == "set_input_files" and selector:
            loc = selector_safe.upper()
            locators[loc] = selector
            method_name = f"upload_{selector_safe}"
            method_args = ["file_path"]
            body_lines.append(f"self.page.set_input_files(self.{loc}, file_path)")

        elif action == "set_input_files":
            base = build_target_call()
            if base:
                method_name = f"upload_{selector_safe}"
                method_args = ["file_path"]
                body_lines.append(f"{base}.set_input_files(file_path)")

        elif action == "close":
            method_name = "close_page"
            body_lines.append("self.page.close()")

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
            "has_assertions": False,
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
            if action_info.get("method_lines"):
                action_info["method_lines"][0] = f"def {method_key}({', '.join(['self'] + action_info.get('method_args', []))}):"
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
        init_file = pages_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

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
            'from playwright.sync_api import expect',
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

        for index, step in enumerate(annotated, start=1):
            action = step.get("action")
            page_class = step.get("page_class")
            method_name = step.get("method_name")
            assertions = step.get("assertions", [])

            if action == "goto":
                raw_text = self.ACTION_MAP[action].format(**step)
                step_text = self._escape_single_quotes(self._normalize_step_text(raw_text))
                func_name = f"step_{index:03d}_open_{self._safe_name(step.get('page_name'))}"
                lines.extend([
                    '',
                    f"@given('{step_text}')",
                    f"def {func_name}(page):",
                    f"    page_obj = {page_class}(page)",
                    "    page_obj.open()",
                    "    logger.info('Opened page')",
                ])
                continue

            if action in ("click", "right_click", "dblclick", "hover", "check", "uncheck"):
                raw_text = self.ACTION_MAP[action].format(**step)
                step_text = self._escape_single_quotes(self._normalize_step_text(raw_text))
                func_name = f"step_{index:03d}_{action}_{self._safe_name(step.get('element_name'))}"
                decorator = f"@when('{step_text}')"
                method_call = f"    {page_class}(page).{method_name}()"

            elif action in ("fill", "type"):
                pattern_text = f"the user {'enters' if action == 'fill' else 'types'} '{{value}}' into {step.get('element_name')}"
                pattern_text = self._escape_double_quotes(pattern_text)
                func_name = f"step_{index:03d}_enter_{self._safe_name(step.get('element_name'))}"
                decorator = f"@when(parsers.parse(\"{pattern_text}\"))"
                method_call = f"    {page_class}(page).{method_name}(value)"

            elif action == "press":
                pattern_text = f"the user presses '{{key}}' in {step.get('element_name')}"
                pattern_text = self._escape_double_quotes(pattern_text)
                func_name = f"step_{index:03d}_press_{self._safe_name(step.get('element_name'))}"
                decorator = f"@when(parsers.parse(\"{pattern_text}\"))"
                method_call = f"    {page_class}(page).{method_name}(key)"

            elif action == "select_option":
                pattern_text = f"the user selects '{{value}}' from {step.get('element_name')}"
                pattern_text = self._escape_double_quotes(pattern_text)
                func_name = f"step_{index:03d}_select_{self._safe_name(step.get('element_name'))}"
                decorator = f"@when(parsers.parse(\"{pattern_text}\"))"
                method_call = f"    {page_class}(page).{method_name}(value)"

            elif action == "set_input_files":
                pattern_text = f"the user uploads '{{file_path}}' to {step.get('element_name')}"
                pattern_text = self._escape_double_quotes(pattern_text)
                func_name = f"step_{index:03d}_upload_{self._safe_name(step.get('element_name'))}"
                decorator = f"@when(parsers.parse(\"{pattern_text}\"))"
                method_call = f"    {page_class}(page).{method_name}(file_path)"

            elif action == "close":
                raw_text = self.ACTION_MAP[action].format(**step)
                step_text = self._escape_single_quotes(self._normalize_step_text(raw_text))
                func_name = f"step_{index:03d}_close_page"
                decorator = f"@when('{step_text}')"
                method_call = f"    {page_class}(page).{method_name}()"

            else:
                continue

            lines.extend([
                '',
                decorator,
                f"def {func_name}(page{', value' if action in ('fill', 'type', 'select_option') else ''}{', key' if action == 'press' else ''}{', file_path' if action == 'set_input_files' else ''}):",
                method_call,
            ])

            for assertion in assertions:
                normalized = self._normalize_assertion_line(assertion, target="page")
                lines.append(f"    {normalized}")

        steps_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    feature_file = processor.ask_feature_file(
        "Feature File", ".feature", [("Feature Files", "*.feature")]
    )
    if not feature_file:
        print("Operation aborted by user.")
        raise SystemExit(0)
    steps_file = processor.ask_file(
        "Steps File", ".py", [("Python Files", "*.py")]
    )

    steps = processor.extract_steps_from_codegen(args.codegen)
    _, annotated_steps = processor.prepare_page_definitions(steps)
    processor.generate_feature_file(annotated_steps, feature_file, args.scenario)

    pages_dir = processor.ask_dir("Select Pages Folder")
    processor.generate_page_class_files(annotated_steps, pages_dir)
    processor.generate_step_definitions_file(annotated_steps, steps_file, pages_dir)

    print(
        f"BDD scenario, step definitions, and page classes written to {feature_file}, {steps_file}, and {pages_dir}"
    )