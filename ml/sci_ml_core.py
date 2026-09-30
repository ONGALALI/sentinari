import torch
import torch.nn as nn
import torch.optim as optim
import time

# 1. Device Verification (Crucial for a new rig setup)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("="*60)
print(f"SYSTEM STATUS: Scientific Pipeline Active")
print(f"COMPUTE DEVICE: {device}")
if torch.cuda.is_available():
    print(f"GPU MODEL: {torch.cuda.get_device_name(0)}")
    # Enables PyTorch's internal optimization flag for Blackwell/Ada architectures
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
print("="*60)

# 2. Universal Physics-Informed / Scientific Neural Network
class UniversalSciNet(nn.Module):
    def __init__(self, input_dim, hidden_dims, output_dim):
        super(UniversalSciNet, self).__init__()
        
        layers = []
        prev_dim = input_dim
        for h_dim in hidden_dims:
            layers.append(nn.Linear(prev_dim, h_dim))
            # SiLU (Swish) or Tanh are standard for continuous scientific gradients
            layers.append(nn.SiLU()) 
            prev_dim = h_dim
        layers.append(nn.Linear(prev_dim, output_dim))
        
        self.network = nn.Sequential(*layers)
        
    def forward(self, x):
        return self.network(x)

# 3. Flexible Simulation Parameters (Adaptable to any scientific field)
INPUT_FEATURES = 4    # Example: X, Y, Z coordinates + Time (T)
OUTPUT_FEATURES = 2   # Example: Pressure + Velocity, or Chemical Concentration
SAMPLE_SIZE = 10000

# Generate synthetic experimental coordinates
# FIX (§48): requires_grad removed here. Data and labels must NOT carry grad —
# building y_experimental from a grad-tracked tensor tied the LABELS into the
# autograd graph; the first backward() freed it and epoch 2 crashed with
# "backward through the graph a second time". Grad tracking for the physics
# residual is created fresh per call inside compute_scientific_loss(),
# which is the correct PINN pattern.
X_experimental = torch.randn(SAMPLE_SIZE, INPUT_FEATURES, dtype=torch.float32).to(device)
y_experimental = torch.sin(X_experimental[:, :OUTPUT_FEATURES]) # Simulating a natural wave law

# 4. Model Initialization
# Structure: Input layer -> 3 Hidden layers of 128 neurons -> Output layer
model = UniversalSciNet(input_dim=INPUT_FEATURES, hidden_dims=[128, 128, 128], output_dim=OUTPUT_FEATURES).to(device)
optimizer = optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
criterion = nn.MSELoss()

# 5. Scientific Partial Derivative Constraint Function
def compute_scientific_loss(model, inputs):
    """
    Evaluates custom partial differential equations (PDEs) or boundary rules.
    Calculates derivatives of outputs with respect to inputs across the GPU.
    """
    # Clone inputs to safely track gradients
    inputs = inputs.clone().detach().requires_grad_(True)
    outputs = model(inputs)
    
    # Target the first output variable (e.g., system energy state)
    target_output = outputs[:, 0].unsqueeze(1)
    
    # Calculate Jacobians/Gradients (e.g., changes over space/time)
    grads = torch.autograd.grad(
        outputs=target_output,
        inputs=inputs,
        grad_outputs=torch.ones_like(target_output),
        create_graph=True,
        retain_graph=True,
        only_inputs=True
    )[0]
    
    # Generic conservation law placeholder: 
    # E.g., The rate of change across dimensions must balance to a specific equilibrium
    governing_equation_residual = grads[:, 0] + grads[:, 1] - 0.1 * target_output.squeeze()
    
    return torch.mean(governing_equation_residual ** 2)

# 6. Benchmark Execution Loop
epochs = 1000
start_time = time.time()

print("\nProcessing training iterations across CUDA Cores...")
for epoch in range(1, epochs + 1):
    optimizer.zero_grad()
    
    # Calculate standard data fit loss
    predictions = model(X_experimental)
    loss_data = criterion(predictions, y_experimental)
    
    # Calculate physical/mathematical constraint consistency loss
    loss_physics = compute_scientific_loss(model, X_experimental)
    
    # Combine losses
    total_loss = loss_data + (0.2 * loss_physics)
    
    # Optimize network parameters
    total_loss.backward()
    optimizer.step()
    
    if epoch % 200 == 0 or epoch == 1:
        print(f"Epoch: {epoch:4d}/{epochs} | Combined Loss: {total_loss.item():.6f} | Physics Residual: {loss_physics.item():.6f}")

end_time = time.time()
print("="*60)
print(f"Pipeline executed successfully in: {end_time - start_time:.2f} seconds.")
print("="*60)
