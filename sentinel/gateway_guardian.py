class GatewayGuardian:
    """
    Exact-match only, per Prof Wep's decision (2026-09-14):
    fuzzy matching (rapidfuzz) and API-name routing were considered
    and dropped in favor of a single exact-match field router.
    """
    def __init__(self, domains, api_registry, sentinel):
        self.domains = domains
        self.api_registry = api_registry
        self.sentinel = sentinel

    def route_field(self, field):
        clean_field = field.strip().title()
        for domain, fields in self.domains.items():
            if clean_field in fields:
                decision = f"{clean_field} routed to {domain}"
                self.sentinel.record(decision)
                return decision
        decision = f"{clean_field} not recognized — Sentinel review required"
        self.sentinel.record(decision)
        return decision

    def route_api(self, api_name, payload=None):
        domain = self.api_registry.get(api_name, "Unknown Domain")
        decision = f"API {api_name} routed to {domain}"
        self.sentinel.record(decision)
        return {"domain": domain, "payload": payload}