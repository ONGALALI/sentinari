class GuardianDomain:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields

    def show_fields(self):
        return f"{self.name} oversees: {', '.join(self.fields)}"