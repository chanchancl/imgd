
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

def Ask(prompt = ""):
    if prompt != "":
        print(prompt)
    ans = input().strip()
    if ans == "" or ans not in "yY":
        return False
    return True