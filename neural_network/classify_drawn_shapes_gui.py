import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw

class NeuralNetwork:
    """Neural Network for Shape Classification"""
    
    def __init__(self):
        # Xavier initialization
        self.W1 = np.random.randn(256, 128) * np.sqrt(2.0 / 256)
        self.b1 = np.zeros((1, 128))
        self.W2 = np.random.randn(128, 64) * np.sqrt(2.0 / 128)
        self.b2 = np.zeros((1, 64))
        self.W3 = np.random.randn(64, 32) * np.sqrt(2.0 / 64)
        self.b3 = np.zeros((1, 32))
        self.W4 = np.random.randn(32, 4) * np.sqrt(2.0 / 32)
        self.b4 = np.zeros((1, 4))
        self.learning_rate = 0.1
    
    def relu(self, x):
        return np.maximum(0, x)
    
    def relu_derivative(self, x):
        return (x > 0).astype(float)
    
    def sigmoid(self, x):
        return 1 / (1 + np.exp(-np.clip(x, -500, 500)))
    
    def sigmoid_derivative(self, x):
        return x * (1 - x)
    
    def forward(self, X):
        self.z1 = np.dot(X, self.W1) + self.b1
        self.a1 = self.relu(self.z1)
        self.z2 = np.dot(self.a1, self.W2) + self.b2
        self.a2 = self.relu(self.z2)
        self.z3 = np.dot(self.a2, self.W3) + self.b3
        self.a3 = self.relu(self.z3)
        self.z4 = np.dot(self.a3, self.W4) + self.b4
        self.output = self.sigmoid(self.z4)
        return self.output
    
    def backward(self, X, y):
        m = X.shape[0]
        dz4 = (self.output - y) * self.sigmoid_derivative(self.output)
        dW4 = np.dot(self.a3.T, dz4) / m
        db4 = np.sum(dz4, axis=0, keepdims=True) / m
        
        dz3 = np.dot(dz4, self.W4.T) * self.relu_derivative(self.z3)
        dW3 = np.dot(self.a2.T, dz3) / m
        db3 = np.sum(dz3, axis=0, keepdims=True) / m
        
        dz2 = np.dot(dz3, self.W3.T) * self.relu_derivative(self.z2)
        dW2 = np.dot(self.a1.T, dz2) / m
        db2 = np.sum(dz2, axis=0, keepdims=True) / m
        
        dz1 = np.dot(dz2, self.W2.T) * self.relu_derivative(self.z1)
        dW1 = np.dot(X.T, dz1) / m
        db1 = np.sum(dz1, axis=0, keepdims=True) / m
        
        self.W4 -= self.learning_rate * dW4
        self.b4 -= self.learning_rate * db4
        self.W3 -= self.learning_rate * dW3
        self.b3 -= self.learning_rate * db3
        self.W2 -= self.learning_rate * dW2
        self.b2 -= self.learning_rate * db2
        self.W1 -= self.learning_rate * dW1
        self.b1 -= self.learning_rate * db1
    
    def train(self, X, y, epochs=200):
        for epoch in range(epochs):
            self.forward(X)
            self.backward(X, y)
    
    def predict(self, X):
        return self.forward(X)


def generate_circle(size=16):
    grid = np.zeros((size, size))
    cx, cy = size // 2, size // 2
    radius = size // 3
    for y in range(size):
        for x in range(size):
            dist = np.sqrt((x - cx)**2 + (y - cy)**2)
            if abs(dist - radius) < 1.2:
                grid[y, x] = 1
    return grid.flatten()


def generate_triangle(size=16):
    grid = np.zeros((size, size))
    for y in range(size):
        for x in range(size):
            if abs(x - size // 2 - (y - 2) * 0.87) < 0.8 and y > 2:
                grid[y, x] = 1
            if abs(x - size // 2 + (y - 2) * 0.87) < 0.8 and y > 2:
                grid[y, x] = 1
            if y > size - 4 and y < size - 2 and x > 2 and x < size - 3:
                grid[y, x] = 1
    return grid.flatten()


def generate_square(size=16):
    grid = np.zeros((size, size))
    margin = 3
    for y in range(size):
        for x in range(size):
            if (x == margin or x == size - margin - 1) and (margin <= y <= size - margin - 1):
                grid[y, x] = 1
            if (y == margin or y == size - margin - 1) and (margin <= x <= size - margin - 1):
                grid[y, x] = 1
    return grid.flatten()


class ShapeClassifierApp:
    """GUI Application for Shape Classification"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Shape Classifier Neural Network")
        self.root.geometry("800x600")
        
        # Create neural network and train it
        self.nn = None
        self.train_network()
        
        # Drawing canvas
        self.canvas_size = 300
        self.image = Image.new("L", (self.canvas_size, self.canvas_size), 255)
        self.draw = ImageDraw.Draw(self.image)
        
        # Create UI
        self.create_widgets()
        
        # Mouse tracking
        self.last_x = None
        self.last_y = None
    
    def train_network(self):
        """Train the neural network"""
        print("Training neural network...")
        X_train = []
        y_train = []
        
        for _ in range(100):
            X_train.append(generate_circle())
            y_train.append([1, 0, 0, 0])
            X_train.append(generate_triangle())
            y_train.append([0, 1, 0, 0])
            X_train.append(generate_square())
            y_train.append([0, 0, 1, 0])
        
        X_train = np.array(X_train)
        y_train = np.array(y_train)
        
        self.nn = NeuralNetwork()
        self.nn.train(X_train, y_train, epochs=200)
        print("Training complete!")
    
    def create_widgets(self):
        """Create GUI widgets"""
        # Title
        title = tk.Label(self.root, text="Shape Classifier Neural Network", 
                        font=("Arial", 20, "bold"), pady=10)
        title.pack()
        
        subtitle = tk.Label(self.root, text="Draw a circle, triangle, or square", 
                           font=("Arial", 12), pady=5)
        subtitle.pack()
        
        # Canvas for drawing
        self.canvas = tk.Canvas(self.root, width=self.canvas_size, 
                               height=self.canvas_size, bg="white", 
                               cursor="crosshair", bd=2, relief="solid")
        self.canvas.pack(pady=10)
        
        # Bind mouse events
        self.canvas.bind("<Button-1>", self.start_draw)
        self.canvas.bind("<B1-Motion>", self.draw_line)
        self.canvas.bind("<ButtonRelease-1>", self.stop_draw)
        
        # Buttons
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)
        
        classify_btn = tk.Button(button_frame, text="Classify Shape", 
                                command=self.classify, bg="#4CAF50", 
                                fg="white", font=("Arial", 12, "bold"),
                                padx=20, pady=10)
        classify_btn.pack(side=tk.LEFT, padx=5)
        
        clear_btn = tk.Button(button_frame, text="Clear Canvas", 
                             command=self.clear_canvas, bg="#f44336", 
                             fg="white", font=("Arial", 12, "bold"),
                             padx=20, pady=10)
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        # Results frame
        self.result_frame = tk.Frame(self.root, pady=10)
        self.result_frame.pack(fill=tk.BOTH, expand=True, padx=20)
        
        self.result_label = tk.Label(self.result_frame, text="", 
                                     font=("Arial", 16, "bold"))
        self.result_label.pack()
        
        self.confidence_label = tk.Label(self.result_frame, text="", 
                                        font=("Arial", 12))
        self.confidence_label.pack()
    
    def start_draw(self, event):
        self.last_x = event.x
        self.last_y = event.y
    
    def draw_line(self, event):
        if self.last_x and self.last_y:
            # Draw on canvas
            self.canvas.create_line(self.last_x, self.last_y, event.x, event.y,
                                   width=8, fill="black", capstyle=tk.ROUND,
                                   smooth=tk.TRUE)
            # Draw on PIL image
            self.draw.line([self.last_x, self.last_y, event.x, event.y],
                          fill=0, width=8)
            
        self.last_x = event.x
        self.last_y = event.y
    
    def stop_draw(self, event):
        self.last_x = None
        self.last_y = None
    
    def clear_canvas(self):
        self.canvas.delete("all")
        self.image = Image.new("L", (self.canvas_size, self.canvas_size), 255)
        self.draw = ImageDraw.Draw(self.image)
        self.result_label.config(text="")
        self.confidence_label.config(text="")
    
    def classify(self):
        """Classify the drawn shape"""
        # Resize image to 16x16
        img_resized = self.image.resize((16, 16), Image.Resampling.LANCZOS)
        img_array = np.array(img_resized).flatten()
        
        # Normalize (invert so black=1, white=0)
        img_array = 1 - (img_array / 255.0)
        
        # Predict
        prediction = self.nn.predict(img_array.reshape(1, -1))[0]
        
        # Get results
        shape_names = ['Circle', 'Triangle', 'Square', 'Undefined']
        max_idx = np.argmax(prediction)
        confidence = prediction[max_idx] * 100
        
        predicted_shape = shape_names[max_idx] if confidence > 60 else 'Undefined'
        
        # Display results
        self.result_label.config(text=f"Prediction: {predicted_shape}",
                                fg="#2196F3")
        
        scores_text = (f"Confidence: {confidence:.1f}%\n\n"
                      f"Circle: {prediction[0]*100:.1f}%\n"
                      f"Triangle: {prediction[1]*100:.1f}%\n"
                      f"Square: {prediction[2]*100:.1f}%")
        
        self.confidence_label.config(text=scores_text)


def main():
    """Run the application"""
    root = tk.Tk()
    app = ShapeClassifierApp(root)
    root.mainloop()


if __name__ == "__main__":
    print("=" * 50)
    print("SHAPE CLASSIFIER - Starting GUI...")
    print("=" * 50)
    main()