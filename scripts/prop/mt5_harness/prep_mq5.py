"""Turn an EA .mq5 into a C++ struct that compiles against mql_shim.h.

Only mechanical rewrites (no logic changes):
  * drop #property / #include, `input` keyword -> struct member (+ SetInput() for overrides)
  * dynamic arrays  T a[];  T a[][N];  -> MqlArray<T> / MqlArray2<T,N> (bounds checked like MQL5)
  * fixed arrays    T a[N];           -> MqlFixed<T,N>
  * PrintFormat/StringFormat(...)     -> PrintFormatC/StringFormatC with CV() around each argument
    so g++ -Wformat checks the argument types against the format string; %I64d -> %lld
  * reports assignments to input variables (illegal in MQL5)
"""
import re, sys

src, dst, name = sys.argv[1], sys.argv[2], sys.argv[3]
code = open(src, encoding="utf-8").read()

lines = []
inputs = []
for ln in code.split("\n"):
    s = ln.strip()
    if s.startswith("#property") or s.startswith("#include"):
        continue
    m = re.match(r"^\s*input\s+(\w+)\s+(\w+)\s*=\s*([^;]+);", ln)
    if m:
        inputs.append((m.group(1), m.group(2)))
        ln = re.sub(r"^\s*input\s+", "", ln)
    lines.append(ln)
code = "\n".join(lines)

T = r"(int|double|string|MqlRates|long|datetime|bool|ulong)"
code = re.sub(T + r"\s+(\w+)\[\]\[(\d+)\]\s*;", r"MqlArray2<\1,\3> \2;", code)
code = re.sub(T + r"\s+(\w+)\[\]\s*,\s*(\w+)\[\]\s*;", r"MqlArray<\1> \2, \3;", code)
code = re.sub(T + r"\s+(\w+)\[\]\s*;", r"MqlArray<\1> \2;", code)
code = re.sub(T + r"\s+(\w+)\[(\d+)\]\s*;", r"MqlFixed<\1,\3> \2;", code)
left = re.findall(r"\w+\s+\w+\[[^\]]*\]\s*[;,=]", code)
if left:
    print("WARNING: array declarations not converted:", left)


def split_args(s):
    out, depth, cur, q = [], 0, "", None
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            cur += c
            if c == "\\":
                cur += s[i + 1]; i += 2; continue
            if c == q:
                q = None
        elif c in "\"'":
            q = c; cur += c
        elif c in "([":
            depth += 1; cur += c
        elif c in ")]":
            depth -= 1; cur += c
        elif c == "," and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += c
        i += 1
    out.append(cur)
    return out


def rewrite_calls(code, fname, newname):
    res, i = "", 0
    pat = re.compile(r"\b" + fname + r"\s*\(")
    while True:
        m = pat.search(code, i)
        if not m:
            res += code[i:]
            return res
        res += code[i:m.start()]
        j, depth, q = m.end(), 1, None
        while depth:
            c = code[j]
            if q:
                if c == "\\":
                    j += 2; continue
                if c == q:
                    q = None
            elif c in "\"'":
                q = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        inner = code[m.end():j - 1]
        args = split_args(inner)
        fmt = args[0].replace("%I64d", "%lld").replace("%I64u", "%llu")
        rest = ", ".join("CV(" + a.strip() + ")" for a in args[1:])
        res += newname + "(" + fmt + (", " + rest if rest else "") + ")"
        i = j


code = rewrite_calls(code, "PrintFormat", "PrintFormatC")
code = rewrite_calls(code, "StringFormat", "StringFormatC")

# inputs are read-only in MQL5
for _, nm in inputs:
    for m in re.finditer(r"\b" + nm + r"\s*(=|\+=|-=|\*=|/=|\+\+|--)(?!=)", code):
        ctx = code[max(0, m.start() - 60):m.end() + 20].replace("\n", " ")
        if re.search(r"(double|int|bool|string|long)\s+" + nm + r"\s*=", ctx):
            continue
        print("ERROR: assignment to input", nm, "::", ctx)

setin = ["void SetInput(const std::string& k, const std::string& v)", "  {"]
for ty, nm in inputs:
    if ty == "string":
        conv = "v"
    elif ty == "bool":
        conv = '(v == "true" || v == "1")'
    elif ty in ("int", "long"):
        conv = "atoll(v.c_str())"
    else:
        conv = "atof(v.c_str())"
    setin.append(f'   if(k == "{nm}") {{ {nm} = {conv}; return; }}')
setin.append('   fprintf(stderr, "unknown input %s\\n", k.c_str()); exit(2);')
setin.append("  }")

out = f"// generated from {src} by prep_mq5.py\nstruct {name}\n{{\n" + code + "\n" + "\n".join(setin) + "\n};\n"
open(dst, "w").write(out)
print(f"{dst}: {len(inputs)} inputs")
