from sentinel import domains, api_registry, Sentinel, GatewayGuardian, benchmarks, trace_chain

sentinel = Sentinel()
gateway = GatewayGuardian(domains, api_registry, sentinel)

print(gateway.route_field("Physics"))
print(gateway.route_field("Biology"))
print(gateway.route_field("Cybernetics"))
print(gateway.route_api("weather_api"))
print(trace_chain("Physics"))
print(benchmarks.get("Physics"))
print("---LOG---")
print(sentinel.show_log())