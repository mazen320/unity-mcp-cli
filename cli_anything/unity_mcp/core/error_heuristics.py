"""C# and Unity compiler error heuristics for debug doctor.

Maps known error codes and message patterns to human-readable explanations,
likely causes, and targeted CLI fix suggestions.

Used by build_debug_doctor_report() to upgrade the raw "Compilation Issues"
finding into something actionable.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ── Known C# compiler error codes ─────────────────────────────────────────────
# Each entry: code → {title, cause, fix_hint, fix_command_template}
# fix_command_template may contain {port_suffix}.

_CS_HEURISTICS: Dict[str, Dict[str, str]] = {
    "CS0246": {
        "title": "Missing Type or Namespace",
        "cause": (
            "A type, class, or namespace could not be found. "
            "Common causes: missing 'using' directive, missing Assembly Definition "
            "reference, or a package that isn't installed."
        ),
        "fix_hint": (
            "Check the using directives at the top of the file. "
            "If the type is in another assembly, add its .asmdef to this assembly's references. "
            "If it's from a package, verify the package is installed."
        ),
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0103": {
        "title": "Undefined Name in Scope",
        "cause": (
            "A name (variable, method, or type) does not exist in the current context. "
            "Usually a typo, a missing 'using' directive, or a variable declared in a different scope."
        ),
        "fix_hint": "Check spelling, ensure the variable is in scope, and verify any required 'using' directives.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS1061": {
        "title": "Member Not Found on Type",
        "cause": (
            "A method, property, or field doesn't exist on the type you're calling it on. "
            "Often caused by an API change, a typo, or calling a method on the wrong type."
        ),
        "fix_hint": (
            "Check the Unity or package version — APIs change between versions. "
            "Verify the variable type is what you expect."
        ),
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0234": {
        "title": "Type or Namespace Missing from Package",
        "cause": (
            "A namespace or type doesn't exist under the specified parent namespace. "
            "Usually means a package isn't installed or a 'using' alias is wrong."
        ),
        "fix_hint": "Verify the package is installed and the namespace spelling matches the API docs.",
        "fix_command_template": "cli-anything-unity-mcp --json tool unity_packages_list{port_suffix}",
    },
    "CS0029": {
        "title": "Type Conversion Error",
        "cause": "Cannot implicitly convert one type to another. An explicit cast or conversion method is needed.",
        "fix_hint": "Add an explicit cast like `(TargetType)value` or use a conversion method.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0266": {
        "title": "Implicit Conversion Not Possible",
        "cause": "Similar to CS0029 — the types are not implicitly compatible and need an explicit cast.",
        "fix_hint": "Add an explicit cast or use `as` for reference types.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0120": {
        "title": "Instance Required for Non-Static Member",
        "cause": "You're calling an instance method or property as if it were static, without an object reference.",
        "fix_hint": "Either make the member static, or call it on an instance of the class.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0117": {
        "title": "Type Has No Such Definition",
        "cause": "A static member (field, method, property) was accessed but doesn't exist on that type.",
        "fix_hint": "Check spelling and whether the member is static. It may have been renamed in a newer API.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0161": {
        "title": "Not All Code Paths Return a Value",
        "cause": "A method declares a return type but some code paths don't hit a return statement.",
        "fix_hint": "Add a return statement for every possible code path, or add a default return at the end.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0165": {
        "title": "Use of Unassigned Variable",
        "cause": "A local variable is read before it has been assigned a value.",
        "fix_hint": "Initialize the variable when you declare it, e.g. `int x = 0;`",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0428": {
        "title": "Method Group Conversion Error",
        "cause": "A method name was used where a value was expected, likely missing parentheses `()`.",
        "fix_hint": "Add `()` to call the method and get its return value.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS7036": {
        "title": "Missing Required Argument",
        "cause": "A method call is missing one or more required parameters.",
        "fix_hint": "Check the method signature and supply all required arguments.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS1002": {
        "title": "Syntax Error — Missing Semicolon",
        "cause": "A statement is missing a semicolon `;` at the end, or there's a nearby syntax error.",
        "fix_hint": "Look at the line number and the line above it. Add the missing semicolon.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS1003": {
        "title": "Syntax Error — Unexpected Token",
        "cause": "The compiler found an unexpected token. Often a missing brace `{}`, parenthesis, or comma.",
        "fix_hint": "Check bracket and parenthesis pairing around the reported line.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0019": {
        "title": "Operator Cannot Be Applied to These Types",
        "cause": "A binary operator (==, +, -, etc.) is used on types that don't support it.",
        "fix_hint": "Cast one or both sides to compatible types, or override the operator.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0115": {
        "title": "Override Without Matching Base Method",
        "cause": "A method is marked `override` but the base class has no matching virtual or abstract method.",
        "fix_hint": "Remove `override`, change it to `virtual`, or fix the method signature to match the base.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0111": {
        "title": "Duplicate Member Definition",
        "cause": "A method or property is defined more than once with the same signature in the same class.",
        "fix_hint": "Remove or rename one of the duplicate definitions.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0106": {
        "title": "Invalid Modifier",
        "cause": "A modifier (`public`, `static`, `override`, etc.) is used in an invalid location.",
        "fix_hint": "Check the context — some modifiers aren't valid inside interfaces, structs, or nested types.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0619": {
        "title": "Obsolete API Usage",
        "cause": "A method, property, or type is marked [Obsolete] and the replacement is required.",
        "fix_hint": "Check the error message for the suggested replacement. Unity APIs change between major versions.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0618": {
        "title": "Obsolete API Warning (Deprecated)",
        "cause": "A method, property, or type is marked [Obsolete] but still compiles. It will be removed in a future version.",
        "fix_hint": "Migrate to the suggested replacement now to avoid breakage on Unity upgrades.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0649": {
        "title": "Uninitialized Private Field",
        "cause": "A private field is declared but never assigned. In Unity, this is common for [SerializeField] fields assigned via the Inspector.",
        "fix_hint": "If the field is set via Inspector, suppress with `= default!;` or `#pragma warning disable CS0649`. Otherwise, initialize it.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0535": {
        "title": "Interface Member Not Implemented",
        "cause": "A class declares it implements an interface but is missing one or more required members.",
        "fix_hint": "Implement all members defined by the interface. Check the interface definition for the full list.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
    "CS0433": {
        "title": "Duplicate Type in Multiple Assemblies",
        "cause": "The same type exists in two different assemblies. Often caused by duplicate script files or conflicting packages.",
        "fix_hint": "Search the project for duplicate .cs files with the same class name. Remove or rename one copy.",
        "fix_command_template": "cli-anything-unity-mcp --json tool unity_search_assets --params '{{\"searchPattern\": \"*.cs\"}}'{port_suffix}",
    },
    "CS0101": {
        "title": "Duplicate Type in Namespace",
        "cause": "A namespace already contains a definition for this type name. Usually a duplicate file or copy-paste error.",
        "fix_hint": "Search for duplicate class definitions and remove or rename the extra copy.",
        "fix_command_template": "cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
    },
}

# ── Unity-specific runtime/warning patterns ────────────────────────────────────
_UNITY_PATTERNS: List[Dict[str, str]] = [
    {
        "pattern": r"nullreferenceexception",
        "title": "NullReferenceException at Runtime",
        "cause": "A variable is null when the code tries to access a member on it.",
        "fix_hint": (
            "Add a null check before accessing the variable. "
            "If it's a serialized field, make sure it's assigned in the Inspector."
        ),
        "severity": "error",
    },
    {
        "pattern": r"missingreferenceexception",
        "title": "MissingReferenceException at Runtime",
        "cause": "An object was destroyed but a reference to it still exists somewhere.",
        "fix_hint": "Use `if (obj != null)` checks, or use `obj == null` which Unity overrides to detect destroyed objects.",
        "severity": "error",
    },
    {
        "pattern": r"can'?t add component.*because it is already added",
        "title": "Duplicate Component Added",
        "cause": "An AddComponent call is running when the component already exists on the GameObject.",
        "fix_hint": "Use `GetComponent<T>() ?? gameObject.AddComponent<T>()` to avoid duplicates.",
        "severity": "warning",
    },
    {
        "pattern": r"asmdef.*not found|assembly.*definition.*missing",
        "title": "Assembly Definition Not Found",
        "cause": "A .asmdef file references another assembly that doesn't exist or was renamed.",
        "fix_hint": "Open the .asmdef file in the Inspector and fix or remove the broken reference.",
        "severity": "error",
    },
    {
        "pattern": r"shader.*not found|shader.*missing|shader.*failed to compile",
        "title": "Shader Compilation Failure",
        "cause": "A shader failed to compile, often due to a syntax error, missing include, or unsupported feature.",
        "fix_hint": "Check the shader file for syntax errors. For URP/HDRP shaders, ensure you're using the correct shader graph or HLSL variants.",
        "severity": "error",
    },
    {
        "pattern": r"no cameras rendering|no cameras are rendering",
        "title": "No Active Cameras Rendering",
        "cause": "No Camera component is active in the scene, or all cameras have been disabled.",
        "fix_hint": "Ensure at least one Camera GameObject is active. Check if your Main Camera was accidentally deactivated.",
        "severity": "error",
    },
    {
        "pattern": r"failed to load.*\.unity|scene.*could not be loaded",
        "title": "Scene Failed to Load",
        "cause": "A scene file couldn't be found or loaded, often because it's not in the build settings.",
        "fix_hint": "Add the scene to Build Settings (File > Build Settings) or check the scene path.",
        "severity": "error",
    },
    {
        "pattern": r"graph.*is not a dag|circular.*dependency|assembly.*circular",
        "title": "Circular Assembly Dependency",
        "cause": "Two or more .asmdef files reference each other, creating a circular dependency.",
        "fix_hint": "Restructure your assemblies so dependencies flow in one direction only.",
        "severity": "error",
    },
    # ── Serialization errors ─────────────────────────────────────────────────
    {
        "pattern": r"serializationexception|serialization.*error|failed.*deserializ",
        "title": "Serialization Error",
        "cause": "Unity failed to serialize or deserialize data. Common with ScriptableObjects, custom serialized classes, or JSON/binary asset data.",
        "fix_hint": (
            "Ensure all serialized fields use Unity-supported types. "
            "Check for [System.Serializable] on custom classes and avoid Dictionary/HashSet in serialized fields."
        ),
        "severity": "error",
    },
    {
        "pattern": r"type.*is not marked as serializable|not.*serializable",
        "title": "Type Not Serializable",
        "cause": "A field references a type that Unity cannot serialize. Unity requires [System.Serializable] on custom classes used in serialized fields.",
        "fix_hint": "Add [System.Serializable] to the class, or change the field to a Unity-supported type.",
        "severity": "warning",
    },
    {
        "pattern": r"layout.*has changed|layout.*mismatch|serialized.*layout.*changed",
        "title": "Serialized Layout Changed",
        "cause": "A serialized class or struct has changed its layout (fields added/removed/reordered), causing data loss on existing assets.",
        "fix_hint": "Use [FormerlySerializedAs(\"oldName\")] when renaming fields to preserve existing data. Re-import affected assets.",
        "severity": "warning",
    },
    # ── Prefab errors ────────────────────────────────────────────────────────
    {
        "pattern": r"prefab.*missing|missing.*prefab|prefab.*broken|prefab.*corrupt",
        "title": "Missing or Broken Prefab",
        "cause": "A prefab asset is missing, corrupted, or has broken internal references.",
        "fix_hint": "Re-import the prefab (right-click > Reimport). If the source prefab was deleted, recreate it or remove references to it.",
        "severity": "error",
    },
    {
        "pattern": r"prefab.*instance.*invalid|prefab.*override.*error|disconnected.*prefab",
        "title": "Prefab Instance Error",
        "cause": "A prefab instance in the scene has become disconnected from its source prefab, or has invalid overrides.",
        "fix_hint": "Select the broken instance, right-click > Prefab > Reconnect or Unpack Completely to fix.",
        "severity": "warning",
    },
    {
        "pattern": r"nested.*prefab.*error|variant.*prefab.*error",
        "title": "Nested/Variant Prefab Error",
        "cause": "A nested or variant prefab has broken inheritance from its base prefab.",
        "fix_hint": "Open the prefab in Prefab Mode and check its base/parent prefab. Re-link or recreate if the base was moved.",
        "severity": "error",
    },
    # ── Asset import errors ──────────────────────────────────────────────────
    {
        "pattern": r"import.*failed|failed.*import.*asset|asset.*import.*error",
        "title": "Asset Import Failed",
        "cause": "Unity's asset pipeline failed to import one or more assets. Common with corrupted files, unsupported formats, or missing dependencies.",
        "fix_hint": "Right-click the asset > Reimport. Check the Console for the specific file and error. For models/textures, verify the source file is valid.",
        "severity": "error",
    },
    {
        "pattern": r"meta.*file.*missing|\.meta.*not found|missing.*meta",
        "title": "Missing .meta File",
        "cause": "A Unity .meta file is missing for an asset. This breaks GUID references and can cause missing references throughout the project.",
        "fix_hint": "Re-import the asset folder (right-click > Reimport All). Unity will regenerate .meta files, but existing references may break.",
        "severity": "warning",
    },
    {
        "pattern": r"fbx.*error|model.*import.*error|mesh.*import.*fail",
        "title": "Model Import Error",
        "cause": "A 3D model (FBX, OBJ, etc.) failed to import. Common causes: corrupted file, unsupported features, or missing textures.",
        "fix_hint": "Re-export the model from the source application. Check that materials and textures are embedded or co-located with the model file.",
        "severity": "error",
    },
    {
        "pattern": r"texture.*import.*fail|texture.*format.*not supported|texture.*corrupt",
        "title": "Texture Import Error",
        "cause": "A texture file failed to import or is in an unsupported format.",
        "fix_hint": "Verify the texture file is valid (PNG, JPG, TGA, PSD, EXR). Try re-saving from an image editor. Check import settings in the Inspector.",
        "severity": "error",
    },
    {
        "pattern": r"script.*import.*error|script.*compilation.*timeout",
        "title": "Script Import Error",
        "cause": "A C# script failed to import, usually due to a compilation error that blocks the entire assembly.",
        "fix_hint": "Fix the compilation error first — one broken script can block all scripts in the same assembly.",
        "severity": "error",
    },
    # ── Other common Unity patterns ──────────────────────────────────────────
    {
        "pattern": r"stackoverflowexception",
        "title": "Stack Overflow at Runtime",
        "cause": "Infinite recursion or deeply nested calls exhausted the call stack.",
        "fix_hint": "Check for recursive method calls, infinite loops in Update/FixedUpdate, or property getters/setters that call themselves.",
        "severity": "error",
    },
    {
        "pattern": r"outofmemoryexception|out of memory",
        "title": "Out of Memory",
        "cause": "The process ran out of memory. Common with large texture imports, unbounded collections, or memory leaks in Update loops.",
        "fix_hint": "Profile memory usage with Unity Profiler. Check for lists/arrays that grow without bounds. Reduce texture sizes.",
        "severity": "error",
    },
    {
        "pattern": r"addressable.*error|addressable.*not found|addressable.*failed",
        "title": "Addressables Error",
        "cause": "An Addressables operation failed — asset not found, catalog not built, or provider error.",
        "fix_hint": "Rebuild Addressables (Window > Asset Management > Addressables > Build). Verify the asset is marked as Addressable and the key/label is correct.",
        "severity": "error",
    },
]


def _extract_cs_code(message: str) -> Optional[str]:
    """Pull the first CS#### error code out of a compiler message."""
    match = re.search(r"\bCS(\d{4})\b", message, re.IGNORECASE)
    return f"CS{match.group(1)}" if match else None


def _extract_file_and_line(message: str) -> Optional[str]:
    """Try to extract 'Assets/Foo/Bar.cs(42,10)' from a compiler message."""
    match = re.search(r"(Assets/[^\s]+\.cs)\((\d+),\d+\)", message)
    if match:
        return f"{match.group(1)} line {match.group(2)}"
    return None


def analyze_compilation_errors(
    entries: List[Dict[str, Any]],
    port_suffix: str,
) -> List[Dict[str, Any]]:
    """Analyze compilation error entries and return enriched heuristic findings.

    Returns a list of finding dicts (same shape as _finding() output),
    deduplicated by error code so CS0246 doesn't fire 20 times.
    """
    if not entries:
        return []

    seen_codes: set[str] = set()
    findings: list[dict[str, Any]] = []

    for entry in entries:
        message = str(entry.get("message") or "")
        if not message:
            continue

        code = _extract_cs_code(message)
        location = _extract_file_and_line(message)

        # ── Known CS code ──────────────────────────────────────────────────
        if code and code not in seen_codes:
            info = _CS_HEURISTICS.get(code)
            if info:
                seen_codes.add(code)
                detail = f"{info['cause']}\n\n{info['fix_hint']}"
                if location:
                    detail = f"At {location}:\n\n{detail}"
                findings.append(
                    {
                        "severity": "error",
                        "title": f"{code}: {info['title']}",
                        "detail": detail,
                        "command": info["fix_command_template"].format(
                            port_suffix=port_suffix
                        ),
                        "evidence": {
                            "errorCode": code,
                            "rawMessage": message[:200],
                            "location": location,
                        },
                        "heuristic": True,
                    }
                )
                continue

        # ── Unknown CS code — still surface it but without enrichment ──────
        if code and code not in seen_codes:
            seen_codes.add(code)
            findings.append(
                {
                    "severity": "error",
                    "title": f"{code}: Compiler Error",
                    "detail": message[:300],
                    "command": f"cli-anything-unity-mcp --json debug snapshot --console-count 50{port_suffix}",
                    "evidence": {"errorCode": code, "rawMessage": message[:200], "location": location},
                    "heuristic": False,
                }
            )

    return findings


def analyze_console_messages(
    entries: List[Dict[str, Any]],
    port_suffix: str,
) -> List[Dict[str, Any]]:
    """Scan Unity console entries for known runtime error patterns.

    Returns enriched findings for patterns that match.
    Only fires on error/warning entries.
    """
    if not entries:
        return []

    findings: list[dict[str, Any]] = []
    seen_patterns: set[str] = set()

    for entry in entries:
        msg_type = str(entry.get("type") or "").lower()
        if msg_type not in {"error", "warning", "exception"}:
            continue
        message = str(entry.get("message") or "").lower()

        for ph in _UNITY_PATTERNS:
            pattern_key = ph["pattern"]
            if pattern_key in seen_patterns:
                continue
            if re.search(pattern_key, message, re.IGNORECASE):
                seen_patterns.add(pattern_key)
                findings.append(
                    {
                        "severity": ph["severity"],
                        "title": ph["title"],
                        "detail": f"{ph['cause']}\n\n{ph['fix_hint']}",
                        "command": f"cli-anything-unity-mcp --json console --count 50 --type error{port_suffix}",
                        "evidence": {"rawMessage": entry.get("message", "")[:200]},
                        "heuristic": True,
                    }
                )

    return findings


def summarize_compilation_errors(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a compact summary: unique codes, file count, worst message."""
    codes: list[str] = []
    files: set[str] = set()
    for entry in entries:
        msg = str(entry.get("message") or "")
        code = _extract_cs_code(msg)
        if code:
            codes.append(code)
        loc = _extract_file_and_line(msg)
        if loc:
            files.add(loc.split(" line ")[0])

    from collections import Counter
    code_counts = dict(Counter(codes).most_common(5))
    return {
        "uniqueErrorCodes": list(dict.fromkeys(codes)),  # preserve order, deduplicate
        "affectedFiles": sorted(files),
        "errorCodeCounts": code_counts,
        "totalErrors": len(entries),
    }
