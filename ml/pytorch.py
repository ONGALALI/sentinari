import torch
import torch.nn as nn
import torch.optim as optim

# 1. Hardware Verification
# This ensures PyTorch detects your RTX 5070 Ti and its 8960 CUDA Cores
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")
if torch.cuda.is_available():
    print(f"GPU Name: {torch.cuda.get_device_name(0)}")
    print(f"CUDA Capability: {torch.cuda.get_device_capability(0)}")

# 2. Define a generic Scientific Neural Network
# Flexible structure suitable for regression across physics, chemistry, etc.
class ScientificNet(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super(ScientificNet, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, output_size)
        )
        
    def forward(self, x):
        return self.network(x)

# 3. Generate Mock Multi-Field Data (e.g., 10 physical inputs predicting 2 outcomes)
num_samples = 5000
X_dummy = torch.randn(num_samples, 10)
y_dummy = torch.randn(num_samples, 2)

# 4. Initialize Network and Move to GPU VRAM
model = ScientificNet(input_size=10, hidden_size=64, output_size=2).to(device)
criterion = nn.MSELoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)

# 5. Training Loop
epochs = 100
batch_size = 64

print("\nStarting GPU-accelerated training...")
for epoch in range(epochs):
    # Create mini-batches
    permutation = torch.randperm(X_dummy.size()[0])
    
    epoch_loss = 0.0
    for i in range(0, X_dummy.size()[0], batch_size):
        indices = permutation[i:i+batch_size]
        batch_x, batch_y = X_dummy[indices], y_dummy[indices]
        
        # CRITICAL: Push data batches to the RTX 5070 Ti
        batch_x, batch_y = batch_x.to(device), batch_y.to(device)
        
        # Forward pass
        optimizer.zero_grad()
        outputs = model(batch_x)
        loss = criterion(outputs, batch_y)
        
        # Backward pass and optimize
        loss.backward()
        optimizer.step()
        
        epoch_loss += loss.item() * batch_x.size(0)
        
    if (epoch + 1) % 10 == 0:
        total_loss = epoch_loss / num_samples
        print(f"Epoch [{epoch+1}/{epochs}], Loss: {total_loss:.4f}")

print("\nTraining Complete! Your Blackwell GPU successfully processed the pipeline.")
