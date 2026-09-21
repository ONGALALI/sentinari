# === SENTINEL PIPELINE ===

# Domains and Fields
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

# === Sentinel (Commander Logbook) ===
class Sentinel:
    def __init__(self):
        self.log = []
    
    def record(self, message):
        self.log.append(message)
    
    def show_log(self):
        return "\n".join(self.log)

# === Guardian Domain (Specialist) ===
class GuardianDomain:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields
    
    def show_fields(self):
        return f"{self.name} oversees: {', '.join(self.fields)}"

# === Gateway Guardian (Dispatcher / Herbal Filter) ===
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

# === Relationships (Knowledge Chains) ===
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

# === Benchmarks (Gardudians) ===
benchmarks = {
    "Physics": "Guardian of Matter",
    "Biology": "Guardian of Life",
    "Psychology": "Guardian of Mind",
    "Engineering": "Guardian of Tools",
    "Medicine": "Guardian of Survival"
}

def get_guardian(field):
    return benchmarks.get(field, "No Guardian Assigned")

# === Example Run ===
sentinel = Sentinel()
gateway = GatewayGuardian(domains, sentinel)

print(gateway.route_field("Physics"))       # Routed to Foundations of Reality
print(gateway.route_field("Biology"))       # Routed to Life and Biological Systems
print(gateway.route_field("Medicine"))      # Routed to Health, Safety, and Well‑Being
print(gateway.route_field("Cybernetics"))   # Not recognized — Sentinel review required

print(get_guardian("Medicine"))             # Guardian of Survival