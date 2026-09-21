relationships = [
    ("Physics", "Chemistry"),
    ("Chemistry", "Biology"),
    ("Biology", "Medicine"),
    ("Psychology", "Sociology"),
    ("Sociology", "Political Science")
]

def trace_chain(start_field):
    chain = [start_field]
    for rel in relationships:
        if rel[0] == chain[-1]:
            chain.append(rel[1])
    return " → ".join(chain)
