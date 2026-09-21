class Sentinel:
    """Commander logbook — records every routing decision."""
    def __init__(self):
        self.log = []

    def record(self, message):
        self.log.append(message)

    def show_log(self):
        return "\n".join(self.log)