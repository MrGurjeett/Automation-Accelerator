"""Security utilities for the Automation Accelerator framework.

Phase 1 security hardening (issues 1.0 – 1.4):

- SecretStr: a string wrapper that never leaks its value through repr/str/logging
- LogRedactionFilter: a logging filter that masks API-key-like patterns
- sanitize_user_input / escape_prompt_template: prompt-injection prevention
- CodeSafetyValidator / validate_feature_output: AST + deny-list validation
- validate_url / validate_file_path / safe_subprocess: injection-hardened helpers
- InputValidator: comprehensive type/format validation with allowlists
- RBACManager: role-based access control enforcement
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import logging
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


# ────────────────────────────────────────────────────────────────────────────
# SecretStr — safe credential wrapper
# ────────────────────────────────────────────────────────────────────────────

class SecretStr:
    """Wraps a secret so it never appears in repr(), str(), print(), or logs.

    Access the real value explicitly via `.get_secret_value()`.
    """

    __slots__ = ("_secret_value",)

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_secret_value", value)

    # Prevent mutation
    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("SecretStr is immutable")

    def __delattr__(self, _name: str) -> None:
        raise AttributeError("SecretStr is immutable")

    def get_secret_value(self) -> str:
        return object.__getattribute__(self, "_secret_value")

    def __repr__(self) -> str:
        return "SecretStr('********')"

    def __str__(self) -> str:
        return "********"

    def __len__(self) -> int:
        return len(self.get_secret_value())

    def __bool__(self) -> bool:
        return bool(self.get_secret_value())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            return hmac.compare_digest(
                self.get_secret_value(), other.get_secret_value()
            )
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.get_secret_value())


# ────────────────────────────────────────────────────────────────────────────
# Log Redaction Filter — masks secrets that slip into log records
# ────────────────────────────────────────────────────────────────────────────

# Patterns that resemble API keys, bearer tokens, passwords, etc.
_REDACTION_PATTERNS: list[re.Pattern[str]] = [
    # Generic hex API keys (32+ hex chars)
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
    # Bearer tokens
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    # Azure-style keys (base64-ish, 40+ chars)
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
    # Passwords in key=value
    re.compile(r"(?i)(password|passwd|secret|api[_-]?key|token)\s*[=:]\s*\S+"),
    # Connection strings
    re.compile(r"(?i)(connection[_-]?string|dsn|jdbc)\s*[=:]\s*\S+"),
    # Private keys
    re.compile(r"-----BEGIN\s+(RSA |EC )?PRIVATE KEY-----"),
]

_REDACTION_PLACEHOLDER = "***REDACTED***"


class LogRedactionFilter(logging.Filter):
    """Logging filter that redacts potential secrets from log messages."""

    def __init__(self, patterns: list[re.Pattern[str]] | None = None, name: str = "") -> None:
        super().__init__(name)
        self.patterns = patterns or _REDACTION_PATTERNS

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(a) if isinstance(a, str) else a for a in record.args)
        return True

    def _redact(self, text: str) -> str:
        for pattern in self.patterns:
            text = pattern.sub(_REDACTION_PLACEHOLDER, text)
        return text


def install_log_redaction(logger_name: str = "") -> None:
    """Attach `LogRedactionFilter` to the given logger (root by default)."""
    target = logging.getLogger(logger_name)
    # Avoid duplicate filters
    if not any(isinstance(f, LogRedactionFilter) for f in target.filters):
        target.addFilter(LogRedactionFilter())


# ────────────────────────────────────────────────────────────────────────────
# Input Sanitisation — prompt-injection prevention
# ────────────────────────────────────────────────────────────────────────────

# Injection payloads typically try to override system instructions.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>", re.IGNORECASE),
    re.compile(r"\[\s*INST\s*\]|\[\s*/INST\s*\]", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*###?\s*(system|instruction)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"(?:do\s+not|don'?t)\s+follow\s+(your|the|any)\s+(original|initial|system)", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"override\s+(system|instructions?|rules?)", re.IGNORECASE),
    re.compile(r"act\s+as\s+(a\s+)?(different|new|evil|unrestricted)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are\s+", re.IGNORECASE),
    re.compile(r"reveal\s+(your|the)\s+(system\s+)?(prompt|instructions?|rules?)", re.IGNORECASE),
]

# Maximum length for user query input to prevent resource abuse
MAX_QUERY_LENGTH = 5_000


class InputSanitisationError(ValueError):
    """Raised when user input appears to contain injection payloads."""


def sanitize_user_input(text: str, *, max_length: int = MAX_QUERY_LENGTH) -> str:
    """Sanitise and validate a user query before it reaches an LLM prompt.

    Raises:
        InputSanitisationError: if the text contains injection patterns or is too long.

    Returns:
        Cleaned text safe for interpolation into a prompt template.
    """
    if not text or not text.strip():
        raise InputSanitisationError("User query must not be empty.")

    text = text.strip()

    if len(text) > max_length:
        raise InputSanitisationError(
            f"User query exceeds maximum length ({len(text)} > {max_length})."
        )

    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            raise InputSanitisationError(
                f"Potential prompt-injection detected: '{match.group()}'"
            )

    # Strip any stray special delimiters that could confuse the model
    text = re.sub(r"<\|.*?\|>", "", text)

    return text


def escape_prompt_template(text: str) -> str:
    """Escape user-provided text so it cannot break out of a prompt template.

    This wraps user content in explicit delimiters and neutralises
    common role-boundary markers.
    """
    # Neutralise markdown heading-style role markers
    escaped = re.sub(r"(?m)^(#{1,3})\s*(system|user|assistant)\s*$", r"\1 [escaped-role]", text, flags=re.IGNORECASE)
    return escaped


# ────────────────────────────────────────────────────────────────────────────
# LLM Output Validation — AST + deny-list safety checks
# ────────────────────────────────────────────────────────────────────────────

# Dangerous imports and function calls that MUST NOT appear in generated code.
DANGEROUS_IMPORTS: frozenset[str] = frozenset({
    "subprocess",
    "shutil",
    "ctypes",
    "socket",
    "http.server",
    "xmlrpc",
    "pickle",
    "shelve",
    "webbrowser",
    "smtplib",
    "ftplib",
    "telnetlib",
    "antigravity",
    "code",
    "codeop",
    "compileall",
    "importlib",
})

DANGEROUS_CALLS: frozenset[str] = frozenset({
    "eval",
    "exec",
    "compile",
    "execfile",
    "__import__",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "os.system",
    "os.popen",
    "os.exec",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.spawn",
    "os.spawnl",
    "os.spawnle",
    "os.spawnlp",
    "os.spawnlpe",
    "os.spawnv",
    "os.spawnve",
    "os.spawnvp",
    "os.spawnvpe",
    "os.popen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
})


class CodeSafetyError(Exception):
    """Raised when generated code fails safety validation."""

    def __init__(self, message: str, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []


class CodeSafetyValidator:
    """Validates LLM-generated Python code before it is written to disk."""

    def __init__(
        self,
        dangerous_imports: frozenset[str] | None = None,
        dangerous_calls: frozenset[str] | None = None,
    ) -> None:
        self.dangerous_imports = dangerous_imports or DANGEROUS_IMPORTS
        self.dangerous_calls = dangerous_calls or DANGEROUS_CALLS

    def validate(self, source: str, filename: str = "<generated>") -> str:
        """Run all safety checks. Returns the source unchanged if valid.

        Raises:
            CodeSafetyError: if the code fails any check.
        """
        violations: list[str] = []

        # 1. AST parse — is it even valid Python?
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as exc:
            raise CodeSafetyError(
                f"Generated code has syntax errors: {exc}",
                violations=[f"SyntaxError: {exc}"],
            ) from exc

        # 2. Walk AST for dangerous imports
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = self._import_names(node)
                for name in names:
                    if name in self.dangerous_imports or name.split(".")[0] in self.dangerous_imports:
                        violations.append(f"Dangerous import: '{name}'")

            # 3. Check for dangerous function calls
            if isinstance(node, ast.Call):
                call_name = self._call_name(node)
                if call_name and (call_name in self.dangerous_calls or
                                  any(call_name.startswith(d) for d in self.dangerous_calls)):
                    violations.append(f"Dangerous call: '{call_name}'")

        if violations:
            raise CodeSafetyError(
                f"Generated code failed safety validation ({len(violations)} issue(s))",
                violations=violations,
            )

        return source

    @staticmethod
    def _import_names(node: ast.Import | ast.ImportFrom) -> list[str]:
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        module = node.module or ""
        return [module] + [f"{module}.{alias.name}" for alias in node.names]

    @staticmethod
    def _call_name(node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            parts: list[str] = [node.func.attr]
            obj = node.func.value
            while isinstance(obj, ast.Attribute):
                parts.append(obj.attr)
                obj = obj.value
            if isinstance(obj, ast.Name):
                parts.append(obj.id)
            return ".".join(reversed(parts))
        return None


def validate_feature_output(content: str) -> str:
    """Validate that generated feature content looks like valid Gherkin.

    Raises:
        CodeSafetyError: if the output does not conform to expected structure.
    """
    violations: list[str] = []
    stripped = content.strip()

    if not stripped:
        raise CodeSafetyError("Generated feature file is empty.", violations=["Empty output"])

    if not stripped.startswith("Feature:"):
        violations.append("Feature file must begin with 'Feature:' keyword")

    # Must contain at least one scenario
    if not re.search(r"^\s*Scenario( Outline)?:", stripped, re.MULTILINE):
        violations.append("Feature file must contain at least one Scenario")

    # Must contain Given/When/Then
    if not re.search(r"^\s*(Given|When|Then)\s+", stripped, re.MULTILINE):
        violations.append("Feature file must contain Given/When/Then steps")

    if violations:
        raise CodeSafetyError(
            f"Generated feature failed structure validation ({len(violations)} issue(s))",
            violations=violations,
        )

    return content


def compute_file_hash(content: str) -> str:
    """Return SHA-256 hex digest of the content for integrity verification."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ════════════════════════════════════════════════════════════════════════════
# 1.0  URL validation — prevent SSRF / open-redirect
# ════════════════════════════════════════════════════════════════════════════

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def validate_url(url: str, *, allowed_schemes: frozenset[str] | None = None) -> str:
    """Validate and normalise a URL.

    Raises ValueError for unsafe schemes (file://, ftp://, javascript:, data:)
    or malformed input.
    """
    schemes = allowed_schemes or _ALLOWED_SCHEMES
    if not url or not url.strip():
        raise ValueError("URL must not be empty.")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme.lower() not in schemes:
        raise ValueError(
            f"URL scheme '{parsed.scheme}' is not allowed. "
            f"Permitted: {', '.join(sorted(schemes))}"
        )
    if not parsed.netloc and parsed.scheme:
        raise ValueError(f"URL has no host: {url}")
    # Block common bypasses
    if "\\" in url or "@" in url.split("//", 1)[-1].split("/", 1)[0]:
        raise ValueError(f"Suspicious URL characters detected: {url}")
    return url


# ════════════════════════════════════════════════════════════════════════════
# 1.0  File-path traversal prevention
# ════════════════════════════════════════════════════════════════════════════

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def validate_file_path(
    path: str | Path,
    *,
    allowed_root: Path | None = None,
    allowed_extensions: frozenset[str] | None = None,
) -> Path:
    """Ensure *path* resolves within *allowed_root* (project root by default).

    Prevents directory-traversal attacks (``../../etc/passwd``).
    """
    root = (allowed_root or _WORKSPACE_ROOT).resolve()
    resolved = Path(path).resolve()
    if not str(resolved).startswith(str(root)):
        raise ValueError(
            f"Path traversal blocked: {path!r} resolves outside workspace root."
        )
    if allowed_extensions and resolved.suffix.lower() not in allowed_extensions:
        raise ValueError(
            f"File extension '{resolved.suffix}' not in allowed list: {allowed_extensions}"
        )
    return resolved


# ════════════════════════════════════════════════════════════════════════════
# 1.0  Safe subprocess execution
# ════════════════════════════════════════════════════════════════════════════

_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({
    "python", "python3", sys.executable,
    "playwright",
    "npm", "npx",
    "git",
    "pytest",
})


class CommandInjectionError(ValueError):
    """Raised when a subprocess command fails safety checks."""


def safe_subprocess_args(
    cmd: list[str],
    *,
    allowed_executables: frozenset[str] | None = None,
) -> list[str]:
    """Validate subprocess command arguments against an allow-list.

    Returns the *cmd* list unchanged if valid; raises ``CommandInjectionError``
    otherwise.
    """
    execs = allowed_executables or _ALLOWED_EXECUTABLES
    if not cmd:
        raise CommandInjectionError("Command list must not be empty.")

    executable = Path(cmd[0]).name
    if executable not in execs and cmd[0] not in execs:
        raise CommandInjectionError(
            f"Executable '{cmd[0]}' is not on the allow-list: {sorted(execs)}"
        )

    _SHELL_META = re.compile(r"[;|&`$><]")
    for i, arg in enumerate(cmd[1:], start=1):
        if _SHELL_META.search(arg):
            raise CommandInjectionError(
                f"Shell metacharacter in argument {i}: {arg!r}"
            )
    return cmd


# ════════════════════════════════════════════════════════════════════════════
# 1.1  Key derivation & encryption helpers
# ════════════════════════════════════════════════════════════════════════════

def derive_key(
    password: str, salt: bytes | None = None, *, iterations: int = 600_000
) -> tuple[bytes, bytes]:
    """Derive a 256-bit key from *password* using PBKDF2-HMAC-SHA256.

    Returns ``(derived_key, salt)``.
    """
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return dk, salt


def generate_api_token(nbytes: int = 32) -> str:
    """Generate a cryptographically-secure URL-safe API token."""
    return secrets.token_urlsafe(nbytes)


def constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison to prevent side-channel attacks."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ════════════════════════════════════════════════════════════════════════════
# 1.2  Generic Input Validation
# ════════════════════════════════════════════════════════════════════════════


class InputValidationError(ValueError):
    """Raised when input fails format / type / allowlist validation."""


class InputValidator:
    """Comprehensive input validation with allowlist/blocklist filtering."""

    _XSS_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"<script[\s>]", re.IGNORECASE),
        re.compile(r"javascript\s*:", re.IGNORECASE),
        re.compile(r"on(error|load|click|mouseover|focus|blur)\s*=", re.IGNORECASE),
        re.compile(r"<\s*iframe", re.IGNORECASE),
        re.compile(r"<\s*object", re.IGNORECASE),
        re.compile(r"<\s*embed", re.IGNORECASE),
        re.compile(r"<\s*svg[^>]+on\w+\s*=", re.IGNORECASE),
        re.compile(r"expression\s*\(", re.IGNORECASE),
        re.compile(r"url\s*\(\s*['\"]?javascript:", re.IGNORECASE),
    ]

    @classmethod
    def sanitize_html(cls, text: str) -> str:
        """Encode HTML-significant characters to prevent XSS."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    @classmethod
    def check_xss(cls, text: str) -> str:
        """Raise if *text* contains XSS payloads; return text otherwise."""
        for pattern in cls._XSS_PATTERNS:
            m = pattern.search(text)
            if m:
                raise InputValidationError(
                    f"Potential XSS payload detected: '{m.group()}'"
                )
        return text

    _EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    _SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

    @classmethod
    def validate_email(cls, value: str) -> str:
        if not cls._EMAIL_RE.match(value):
            raise InputValidationError(f"Invalid email format: {value!r}")
        return value

    @classmethod
    def validate_slug(cls, value: str, *, max_length: int = 128) -> str:
        """Validate a URL-safe slug (alphanumeric, hyphens, underscores)."""
        if not value or len(value) > max_length:
            raise InputValidationError(
                f"Slug must be 1–{max_length} characters, got {len(value)}."
            )
        if not cls._SLUG_RE.match(value):
            raise InputValidationError(
                f"Slug contains invalid characters: {value!r}"
            )
        return value

    @classmethod
    def validate_int_range(
        cls, value: Any, *, min_val: int = 0, max_val: int = 2**31, name: str = "value"
    ) -> int:
        try:
            v = int(value)
        except (ValueError, TypeError) as exc:
            raise InputValidationError(
                f"{name} must be an integer, got {type(value).__name__}"
            ) from exc
        if v < min_val or v > max_val:
            raise InputValidationError(
                f"{name} must be between {min_val} and {max_val}, got {v}"
            )
        return v

    @classmethod
    def validate_string_length(
        cls, value: str, *, min_len: int = 1, max_len: int = 10_000, name: str = "value"
    ) -> str:
        if not isinstance(value, str):
            raise InputValidationError(f"{name} must be a string.")
        if len(value) < min_len or len(value) > max_len:
            raise InputValidationError(
                f"{name} length must be {min_len}–{max_len}, got {len(value)}."
            )
        return value

    @classmethod
    def validate_allowlist(
        cls, value: str, allowed: frozenset[str] | set[str], *, name: str = "value"
    ) -> str:
        if value not in allowed:
            raise InputValidationError(
                f"{name} '{value}' not in allowed values: {sorted(allowed)}"
            )
        return value

    @classmethod
    def validate_blocklist(
        cls, value: str, blocked: frozenset[str] | set[str], *, name: str = "value"
    ) -> str:
        if value in blocked:
            raise InputValidationError(f"{name} '{value}' is blocked.")
        return value


# ════════════════════════════════════════════════════════════════════════════
# 1.3  Access Control — RBAC
# ════════════════════════════════════════════════════════════════════════════


class AccessDeniedError(PermissionError):
    """Raised when a user lacks the required role/permission."""


class RBACManager:
    """Lightweight role-based access control manager.

    Enforces the principle of least privilege by mapping users to roles and
    roles to granular permissions.
    """

    DEFAULT_ROLES: dict[str, frozenset[str]] = {
        "viewer": frozenset({
            "read:config", "read:features", "read:reports",
        }),
        "tester": frozenset({
            "read:config", "read:features", "read:reports",
            "run:tests", "run:codegen",
        }),
        "developer": frozenset({
            "read:config", "read:features", "read:reports",
            "run:tests", "run:codegen",
            "write:features", "write:steps", "write:pages",
            "run:enhance", "run:index",
        }),
        "admin": frozenset({
            "read:config", "read:features", "read:reports",
            "run:tests", "run:codegen",
            "write:features", "write:steps", "write:pages",
            "run:enhance", "run:index",
            "admin:manage_users", "admin:manage_roles",
            "admin:rotate_keys", "admin:view_audit",
        }),
    }

    def __init__(
        self,
        roles: dict[str, frozenset[str]] | None = None,
        user_roles: dict[str, set[str]] | None = None,
    ) -> None:
        self.roles: dict[str, frozenset[str]] = dict(roles or self.DEFAULT_ROLES)
        self.user_roles: dict[str, set[str]] = dict(user_roles or {})

    def add_role(self, role_name: str, permissions: frozenset[str]) -> None:
        self.roles[role_name] = permissions

    def assign_role(self, user_id: str, role_name: str) -> None:
        if role_name not in self.roles:
            raise ValueError(f"Unknown role: {role_name}")
        self.user_roles.setdefault(user_id, set()).add(role_name)

    def revoke_role(self, user_id: str, role_name: str) -> None:
        if user_id in self.user_roles:
            self.user_roles[user_id].discard(role_name)

    def get_permissions(self, user_id: str) -> frozenset[str]:
        """Return the union of all permissions for a user's assigned roles."""
        perms: set[str] = set()
        for role_name in self.user_roles.get(user_id, set()):
            perms |= self.roles.get(role_name, frozenset())
        return frozenset(perms)

    def has_permission(self, user_id: str, permission: str) -> bool:
        return permission in self.get_permissions(user_id)

    def require_permission(self, user_id: str, permission: str) -> None:
        """Raise ``AccessDeniedError`` if the user lacks *permission*."""
        if not self.has_permission(user_id, permission):
            raise AccessDeniedError(
                f"User '{user_id}' lacks permission '{permission}'."
            )

    def require_any_permission(self, user_id: str, permissions: set[str]) -> None:
        """Raise ``AccessDeniedError`` if the user has none of *permissions*."""
        user_perms = self.get_permissions(user_id)
        if not user_perms & permissions:
            raise AccessDeniedError(
                f"User '{user_id}' lacks any of: {sorted(permissions)}."
            )
