from rapidfuzz import process

class GatewayGuardian:
    def __init__(self, domains, sentinel):
        self.domains = domains
        self.sentinel = sentinel
        # Flatten fields for fuzzy search
        self.all_fields = [field for fields in domains.values() for field in fields]
    
    def route_field(self, field):
        clean_field = field.strip().title()
        
        # Fuzzy match
        match, score, _ = process.extractOne(clean_field, self.all_fields)
        if score > 70:  # threshold for confidence
            for domain, fields in self.domains.items():
                if match in fields:
                    decision = f"{clean_field} interpreted as {match}, routed to {domain}"
                    self.sentinel.record(decision)
                    return decision
        
        decision = f"{clean_field} not recognized — Sentinel review required"
        self.sentinel.record(decision)
        return decision
