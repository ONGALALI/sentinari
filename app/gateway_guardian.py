class GatewayGuardian:
    def __init__(self, domains):
        self.domains = domains
    
    def route_field(self, field):
        for domain, fields in self.domains.items():
            if field in fields:
                return f"{field} routed to {domain}"
        return f"{field} not recognized — needs Sentinel review"
