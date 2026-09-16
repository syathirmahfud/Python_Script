import torch
import torch.nn as nn
import torch.optim as optim

# ----------------------------
# Data
# ----------------------------
X = torch.tensor([[0.,0.],
                  [0.,1.],
                  [1.,0.],
                  [1.,1.]])

y = torch.tensor([[0.],
                  [1.],
                  [1.],
                  [0.]])

# ----------------------------
# Model
# ----------------------------
model = nn.Sequential(
    nn.Linear(2, 4),
    nn.Sigmoid(),
    nn.Linear(4, 1),
    nn.Sigmoid()
)

# ----------------------------
# Loss & Optimizer
# ----------------------------
criterion = nn.MSELoss()
optimizer = optim.SGD(model.parameters(), lr=0.1)

# ----------------------------
# Training loop
# ----------------------------
for epoch in range(10000):
    y_hat = model(X)              # forward pass
    loss = criterion(y_hat, y)    # compute loss

    optimizer.zero_grad()         # reset gradients
    loss.backward()               # backprop (chain rule)
    optimizer.step()              # update weights

# ----------------------------
# Result
# ----------------------------
print(torch.round(model(X)))
