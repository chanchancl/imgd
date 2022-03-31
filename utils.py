
def BuildHeaderFromStr(s: dict):
    headers = {}
    lines = s.split("\n")
    for line in lines:
        if line == "":
            continue
        parts = line.split(": ")
        if parts is None or len(parts) < 2:
            continue
        headers[parts[0]] = parts[1]
    return headers
