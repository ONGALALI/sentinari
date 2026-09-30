import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np

# 1. Hardware Initialization for your RTX 5070 Ti
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Executing Scientific Pipeline on: {device}")

# 2. Fully Configurable Scientific MLP Architecture
class GenericScientificNet(nn.Module):
    def __init__(self, input_dim=1, hidden_layers=[64, 64], output_dim=1):
        super(GenericScientificNet, self).__init__()
        
        layers = []
        in_dim = input_dim
        
        # Build network dynamically based on desired complexity
        for h_dim in hidden_layers:
            layers.append(nn.Linear(in_dim, h_dim))
            # Tanh activation is strongly preferred in SciML for smooth derivatives
            layers.append(nn.Tanh()) 
            in_dim = h_dim
            
        layers.append(nn.Linear(in_dim, output_dim))
        self.network = nn.Sequential(*layers)
        
    def forward(self, x):
        return self.network(x)

# 3. Scientific Data Simulation (e.g., simulating experimental sensor readings)
# Let's assume a generic decaying oscillation curve common in physics/engineering
np.random.seed(42)
x_raw = np.linspace(0, 4, 200).reshape(-1, 1)
y_raw = np.exp(-0.5 * x_raw) * np.sin(2 * np.pi * x_raw)

# Convert to PyTorch Tensors and send to your GPU VRAM
X_experimental = torch.tensor(x_raw, dtype=torch.float32, requires_grad=True).to(device)
y_experimental = torch.tensor(y_raw, dtype=torch.float32).to(device)

# 4. Initialize Network & Optimizer
# Highly flexible: modify layer array to adapt to more complex problem domains
model = GenericScientificNet(input_dim=1, hidden_layers=[128, 128], output_dim=1).to(device)
optimizer = optim.Adam(model.parameters(), lr=0.005)

# 5. Define Custom Scientific / Physical Constraint Loss
def calculate_scientific_loss(model, x_points):
    """
    In scientific ML, we evaluate custom equations at unmeasured 'collocation points'.
    This forces the model to respect derivatives or conservation laws.
    """
    # Ask PyTorch to track operations on these evaluation coordinates
    x_points = x_points.clone().detach().requires_grad_(True)
    
    # Run forward pass
    y_pred = model(x_points)
    
    # Compute the first derivative (dy/dx) using PyTorch Autograd
    dy_dx = torch.autograd.grad(
        y_pred, x_points, 
        grad_outputs=torch.ones_like(y_pred),
        create_graph=True, 
        retain_graph=True
    )[0]
    
    # Generic scientific constraint rule placeholder:
    # E.g., forcing a physical system's derivative curve to stay within bounded behavior.
    # For this template, we balance the physical rate of change against our target rule.
    target_derivative_rule = -0.5 * y_pred
    physics_residual = dy_dx - target_derivative_rule
    
    # Compute mean squared residual of the law violation
    return torch.mean(physics_residual ** 2)

# 6. Hybrid Training Loop (Data-Driven + Physics-Informed)
epochs = 2000
data_weight = 1.0     # How much we trust experimental data
science_weight = 0.1  # How strictly we enforce the mathematical law

print("\nBeginning Scientific Model Optimization...")
for epoch in range(1, epochs + 1):
    optimizer.zero_grad()
    
    # Task A: Calculate Data Loss (fitting the observed physical inputs)
    predictions = model(X_experimental)
    loss_data = nn.MSELoss()(predictions, y_experimental)
    
    # Task B: Calculate Equation/Physics Loss (generalizing across space/time)
    loss_science = calculate_scientific_loss(model, X_experimental)
    
    # Total combined loss
    total_loss = (data_weight * loss_data) + (science_weight * loss_science)
    
    # Backpropagation via Blackwell Tensor Cores
    total_loss.backward()
    optimizer.step()
    
    if epoch % 200 == 0 or epoch == 1:
        print(f"Epoch {epoch:4d}/{epochs} | Total Loss: {total_loss.item():.6f} | "
              f"Data Error: {loss_data.item():.6f} | Sci Constraint Violation: {loss_science.item():.6f}")

print("\nGeneric Scientific Framework complete. Model is now optimized to both data and mathematical constraints.")
