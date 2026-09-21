# === SENTINEL FRAMEWORK ===
# Guardian Domains and Fields

domains = {
    "Foundations of Reality": [
        "Physics", "Chemistry", "Astronomy", "Earth Sciences"
    ],
    "Life and Biological Systems": [
        "Biology", "Genetics", "Neuroscience", "Ecology"
    ],
    "Human Behavior and Society": [
        "Psychology", "Sociology", "Anthropology", "Economics", "Political Science"
    ],
    "Applied Systems and Technology": [
        "Engineering", "Computer Science", "Information Science", "Materials Science"
    ],
    "Health, Safety, and Well‑Being": [
        "Medicine", "Pharmacology", "Public Health", "Environmental Science"
    ]
}

# === Guardian Class ===
class GuardianDomain:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields
    
    def show_fields(self):
        return f"{self.name} oversees: {', '.join(self.fields)}"

# Example usage
big_bear = GuardianDomain("Foundations of Reality", domains["Foundations of Reality"])
print(big_bear.show_fields())

# === Relationships (Chains Across Domains) ===
relationships = [
    ("Physics", "Chemistry"),
    ("Chemistry", "Biology"),
    ("Biology", "Medicine"),
    ("Psychology", "Sociology"),
    ("Sociology", "Political Science")
]

# === Benchmarks (Gardudians) ===
benchmarks = {
    "Physics": "Guardian of Matter",
    "Biology": "Guardian of Life",
    "Psychology": "Guardian of Mind",
    "Engineering": "Guardian of Tools",
    "Medicine": "Guardian of Survival"
}

# === Query Functions ===
def get_domain(field):
    for domain, fields in domains.items():
        if field in fields:
            return domain
    return "Unknown Domain"

def get_guardian(field):
    return benchmarks.get(field, "No Guardian Assigned")

def trace_chain(start_field):
    chain = [start_field]
    for rel in relationships:
        if rel[0] == chain[-1]:
            chain.append(rel[1])
    return " → ".join(chain)

# === Examples ===
print(get_domain("Biology"))          # Life and Biological Systems
print(get_guardian("Medicine"))       # Guardian of Survival
print(trace_chain("Physics"))         # Physics → Chemistry → Biology → Medicine

class Sentinel:
    def __init__(self):
        self.log = []
    
    def record(self, message):
        self.log.append(message)
    
    def show_log(self):
        return "\n".join(self.log)

class GatewayGuardian:
    def __init__(self, domains, sentinel):
        self.domains = domains
        self.sentinel = sentinel
    
    def route_field(self, field):
        # Herbal filter: cleanse input
        clean_field = field.strip().title()
        
        for domain, fields in self.domains.items():
            if clean_field in fields:
                decision = f"{clean_field} routed to {domain}"
                self.sentinel.record(decision)
                return decision
        
        decision = f"{clean_field} not recognized — Sentinel review required"
        self.sentinel.record(decision)
        return decision

class Sentinel:
    def __init__(self):
        self.log = []
    
    def record(self, message):
        self.log.append(message)
    
    def show_log(self):
        return "\n".join(self.log)
class Sentinel:
    def __init__(self):
        self.log = []
    
    def record(self, message):
        self.log.append(message)
    
    def show_log(self):
        return "\n".join(self.log)