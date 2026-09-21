class GatewayGuardian:
    def __init__(self, registry, sentinel):
        self.registry = registry
        self.sentinel = sentinel
    
    def route_api(self, api_name, payload):
        domain = self.registry.get(api_name, "Unknown Domain")
        decision = f"API {api_name} routed to {domain}"
        self.sentinel.record(decision)
        return {"domain": domain, "payload": payload}
