import asyncio

async def process_api(adapter, payload, gateway):
    normalized = adapter.ingest(payload)
    decision = gateway.route_api(adapter.api_name, normalized["data"])
    return decision

async def main(adapters, payloads, gateway):
    tasks = []
    for adapter, payload in zip(adapters, payloads):
        tasks.append(process_api(adapter, payload, gateway))
    results = await asyncio.gather(*tasks)
    return results

# Example adapters
genomics_adapter = APIAdapter("genomics_api", "Life and Biological Systems")
weather_adapter = APIAdapter("weather_api", "Foundations of Reality")

# Run concurrently
results = asyncio.run(main(
    [genomics_adapter, weather_adapter],
    [{"gene":"BRCA1"}, {"temp":22}],
    gateway
))

print(results)

