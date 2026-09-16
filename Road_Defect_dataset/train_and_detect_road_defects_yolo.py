"""
YOLO-based Asphalt Road Defect Detection System
Detects: Potholes, Disintegration, Ravelling, Bleeding, Cracking
"""

import torch
import cv2
import numpy as np
from pathlib import Path
import yaml
from ultralytics import YOLO
import matplotlib.pyplot as plt
from PIL import Image
import albumentations as A
from sklearn.model_selection import train_test_split

# ==================== CONFIGURATION ====================

class Config:
    """Configuration for road defect detection"""
    
    # Class definitions
    CLASSES = {
        0: 'pothole',
        1: 'disintegration', 
        2: 'ravelling',
        3: 'bleeding',
        4: 'cracking'
    }
    
    # Colors for visualization (BGR format)
    COLORS = {
        'pothole': (0, 0, 255),          # Red
        'disintegration': (0, 165, 255),  # Orange
        'ravelling': (0, 255, 255),       # Yellow
        'bleeding': (255, 0, 255),        # Magenta
        'cracking': (255, 255, 0)         # Cyan
    }
    
    # Model parameters
    IMG_SIZE = 640
    BATCH_SIZE = 16
    EPOCHS = 100
    LEARNING_RATE = 0.01
    CONFIDENCE_THRESHOLD = 0.25
    IOU_THRESHOLD = 0.45
    
    # Paths
    DATA_DIR = Path('road_defects_dataset')
    TRAIN_DIR = DATA_DIR / 'images' / 'train'
    VAL_DIR = DATA_DIR / 'images' / 'val'
    TEST_DIR = DATA_DIR / 'images' / 'test'
    WEIGHTS_DIR = Path('weights')
    RESULTS_DIR = Path('results')

# ==================== DATASET PREPARATION ====================

class RoadDefectDataset:
    """Prepare and organize dataset for YOLO training"""
    
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.setup_directories()
    
    def setup_directories(self):
        """Create directory structure for YOLO"""
        dirs = [
            self.data_dir / 'images' / 'train',
            self.data_dir / 'images' / 'val',
            self.data_dir / 'images' / 'test',
            self.data_dir / 'labels' / 'train',
            self.data_dir / 'labels' / 'val',
            self.data_dir / 'labels' / 'test'
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
    
    def create_yaml_config(self):
        """Create YAML configuration file for YOLO"""
        config = {
            'path': str(self.data_dir.absolute()),
            'train': 'images/train',
            'val': 'images/val',
            'test': 'images/test',
            'nc': len(Config.CLASSES),
            'names': list(Config.CLASSES.values())
        }
        
        yaml_path = self.data_dir / 'data.yaml'
        with open(yaml_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        print(f"✓ Created YAML config at {yaml_path}")
        return yaml_path
    
    def augment_image(self, image):
        """Apply data augmentation"""
        transform = A.Compose([
            A.HorizontalFlip(p=0.5),
            A.RandomBrightnessContrast(p=0.3),
            A.GaussNoise(p=0.2),
            A.Blur(blur_limit=3, p=0.2),
            A.RandomGamma(p=0.2),
            A.HueSaturationValue(p=0.3),
            A.CoarseDropout(max_holes=8, max_height=32, max_width=32, p=0.3)
        ], bbox_params=A.BboxParams(format='yolo', label_fields=['class_labels']))
        
        return transform

# ==================== MODEL TRAINING ====================

class RoadDefectTrainer:
    """Train YOLO model for road defect detection"""
    
    def __init__(self, model_size='n'):
        """
        Initialize trainer
        Args:
            model_size: 'n' (nano), 's' (small), 'm' (medium), 'l' (large), 'x' (xlarge)
        """
        Config.WEIGHTS_DIR.mkdir(exist_ok=True)
        Config.RESULTS_DIR.mkdir(exist_ok=True)
        
        self.model_size = model_size
        self.model = YOLO(f'yolov8{model_size}.pt')
        print(f"✓ Loaded YOLOv8{model_size} model")
    
    def train(self, data_yaml, epochs=None, img_size=None):
        """Train the model"""
        epochs = epochs or Config.EPOCHS
        img_size = img_size or Config.IMG_SIZE
        
        print(f"\n{'='*60}")
        print(f"Starting training for {epochs} epochs...")
        print(f"{'='*60}\n")
        
        results = self.model.train(
            data=data_yaml,
            epochs=epochs,
            imgsz=img_size,
            batch=Config.BATCH_SIZE,
            lr0=Config.LEARNING_RATE,
            device=0 if torch.cuda.is_available() else 'cpu',
            patience=20,
            save=True,
            project=str(Config.WEIGHTS_DIR),
            name='road_defect_model',
            exist_ok=True,
            pretrained=True,
            optimizer='AdamW',
            verbose=True,
            seed=42,
            deterministic=True,
            
            # Augmentation parameters
            hsv_h=0.015,
            hsv_s=0.7,
            hsv_v=0.4,
            degrees=0.0,
            translate=0.1,
            scale=0.5,
            shear=0.0,
            perspective=0.0,
            flipud=0.0,
            fliplr=0.5,
            mosaic=1.0,
            mixup=0.0,
        )
        
        print(f"\n✓ Training completed!")
        print(f"Best weights saved to: {Config.WEIGHTS_DIR / 'road_defect_model' / 'weights' / 'best.pt'}")
        
        return results
    
    def validate(self, data_yaml):
        """Validate the model"""
        print("\nValidating model...")
        results = self.model.val(
            data=data_yaml,
            imgsz=Config.IMG_SIZE,
            batch=Config.BATCH_SIZE,
            device=0 if torch.cuda.is_available() else 'cpu'
        )
        return results

# ==================== INFERENCE ====================

class RoadDefectDetector:
    """Detect road defects in images and videos"""
    
    def __init__(self, weights_path):
        """Load trained model"""
        self.model = YOLO(weights_path)
        print(f"✓ Loaded model from {weights_path}")
    
    def detect_image(self, image_path, save_path=None, show=False):
        """
        Detect defects in a single image
        
        Args:
            image_path: Path to input image
            save_path: Path to save annotated image
            show: Whether to display the image
        """
        # Run inference
        results = self.model.predict(
            source=image_path,
            conf=Config.CONFIDENCE_THRESHOLD,
            iou=Config.IOU_THRESHOLD,
            imgsz=Config.IMG_SIZE,
            save=False,
            verbose=False
        )[0]
        
        # Load image
        image = cv2.imread(str(image_path))
        annotated = image.copy()
        
        # Process detections
        detections = []
        boxes = results.boxes
        
        for i, box in enumerate(boxes):
            # Get box coordinates
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            confidence = float(box.conf[0])
            class_id = int(box.cls[0])
            class_name = Config.CLASSES[class_id]
            
            # Store detection info
            detections.append({
                'class': class_name,
                'confidence': confidence,
                'bbox': [x1, y1, x2, y2],
                'class_id': class_id
            })
            
            # Draw on image
            color = Config.COLORS[class_name]
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            
            # Add label
            label = f"{class_name}: {confidence:.2f}"
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(annotated, (x1, y1 - label_h - 10), (x1 + label_w, y1), color, -1)
            cv2.putText(annotated, label, (x1, y1 - 5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        # Save result
        if save_path:
            cv2.imwrite(str(save_path), annotated)
            print(f"✓ Saved annotated image to {save_path}")
        
        # Display
        if show:
            self._show_image(annotated, f"Detected {len(detections)} defects")
        
        return detections, annotated
    
    def detect_video(self, video_path, output_path=None):
        """
        Detect defects in video
        
        Args:
            video_path: Path to input video
            output_path: Path to save annotated video
        """
        cap = cv2.VideoCapture(str(video_path))
        
        # Get video properties
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Setup video writer
        if output_path:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
        
        frame_count = 0
        defect_stats = {name: 0 for name in Config.CLASSES.values()}
        
        print(f"Processing video: {total_frames} frames...")
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_count += 1
            
            # Run inference
            results = self.model.predict(
                source=frame,
                conf=Config.CONFIDENCE_THRESHOLD,
                iou=Config.IOU_THRESHOLD,
                imgsz=Config.IMG_SIZE,
                save=False,
                verbose=False
            )[0]
            
            # Draw detections
            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                confidence = float(box.conf[0])
                class_id = int(box.cls[0])
                class_name = Config.CLASSES[class_id]
                
                defect_stats[class_name] += 1
                
                color = Config.COLORS[class_name]
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                
                label = f"{class_name}: {confidence:.2f}"
                cv2.putText(frame, label, (x1, y1 - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # Write frame
            if output_path:
                out.write(frame)
            
            if frame_count % 30 == 0:
                print(f"Processed {frame_count}/{total_frames} frames...")
        
        cap.release()
        if output_path:
            out.release()
            print(f"✓ Saved annotated video to {output_path}")
        
        # Print statistics
        print("\nDefect Detection Statistics:")
        print("-" * 40)
        for defect, count in defect_stats.items():
            print(f"{defect:20s}: {count:6d} detections")
        print("-" * 40)
        
        return defect_stats
    
    def detect_batch(self, image_dir, output_dir=None):
        """Detect defects in multiple images"""
        image_dir = Path(image_dir)
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        
        image_files = list(image_dir.glob('*.jpg')) + \
                     list(image_dir.glob('*.png')) + \
                     list(image_dir.glob('*.jpeg'))
        
        all_detections = []
        
        print(f"Processing {len(image_files)} images...")
        
        for img_path in image_files:
            save_path = output_dir / f"detected_{img_path.name}" if output_dir else None
            detections, _ = self.detect_image(img_path, save_path)
            all_detections.extend(detections)
            print(f"✓ {img_path.name}: {len(detections)} defects")
        
        return all_detections
    
    def generate_report(self, detections):
        """Generate defect detection report"""
        report = {defect: {'count': 0, 'avg_confidence': 0} 
                 for defect in Config.CLASSES.values()}
        
        for det in detections:
            defect_type = det['class']
            report[defect_type]['count'] += 1
            report[defect_type]['avg_confidence'] += det['confidence']
        
        # Calculate averages
        for defect in report:
            if report[defect]['count'] > 0:
                report[defect]['avg_confidence'] /= report[defect]['count']
        
        # Print report
        print("\n" + "="*60)
        print("ROAD DEFECT DETECTION REPORT")
        print("="*60)
        print(f"{'Defect Type':<20} {'Count':>10} {'Avg Confidence':>15}")
        print("-"*60)
        for defect, stats in report.items():
            print(f"{defect:<20} {stats['count']:>10} {stats['avg_confidence']:>14.2%}")
        print("="*60)
        
        return report
    
    def _show_image(self, image, title="Result"):
        """Display image using matplotlib"""
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        plt.figure(figsize=(12, 8))
        plt.imshow(image_rgb)
        plt.title(title)
        plt.axis('off')
        plt.tight_layout()
        plt.show()

# ==================== MAIN USAGE ====================

def main():
    """Main execution function"""
    
    print("="*60)
    print("YOLO Road Defect Detection System")
    print("="*60)
    
    # Step 1: Setup dataset
    print("\n1. Setting up dataset...")
    dataset = RoadDefectDataset(Config.DATA_DIR)
    data_yaml = dataset.create_yaml_config()
    
    # Step 2: Train model (uncomment to train)
    """
    print("\n2. Training model...")
    trainer = RoadDefectTrainer(model_size='n')  # Use 'n' for fastest, 'x' for best accuracy
    trainer.train(data_yaml, epochs=100)
    trainer.validate(data_yaml)
    """
    
    # Step 3: Run inference
    print("\n3. Running inference...")
    
    # Path to your trained weights
    weights_path = Config.WEIGHTS_DIR / 'road_defect_model' / 'weights' / 'best.pt'
    
    # If weights don't exist, use pretrained YOLO
    if not weights_path.exists():
        print("⚠ Trained weights not found. Using pretrained YOLOv8 for demonstration.")
        weights_path = 'yolov8n.pt'
    
    detector = RoadDefectDetector(weights_path)
    
    # Detect in single image
    # detections, annotated = detector.detect_image('test_image.jpg', 'result.jpg', show=True)
    
    # Detect in video
    # detector.detect_video('road_video.mp4', 'output_video.mp4')
    
    # Detect in batch
    # detections = detector.detect_batch('test_images/', 'results/')
    # detector.generate_report(detections)

if __name__ == "__main__":
    main()

# ==================== USAGE EXAMPLES ====================

"""
TRAINING:
---------
# 1. Prepare your dataset in YOLO format:
#    road_defects_dataset/
#    ├── images/
#    │   ├── train/
#    │   ├── val/
#    │   └── test/
#    └── labels/
#        ├── train/
#        ├── val/
#        └── test/

# 2. Train the model
trainer = RoadDefectTrainer(model_size='n')
trainer.train('road_defects_dataset/data.yaml', epochs=100)

INFERENCE:
----------
# Single image
detector = RoadDefectDetector('weights/road_defect_model/weights/best.pt')
detections, img = detector.detect_image('road.jpg', 'result.jpg', show=True)

# Video
detector.detect_video('road_video.mp4', 'output.mp4')

# Batch processing
detections = detector.detect_batch('test_images/', 'results/')
report = detector.generate_report(detections)

EXPORT MODEL:
-------------
model = YOLO('weights/road_defect_model/weights/best.pt')
model.export(format='onnx')  # or 'torchscript', 'coreml', 'tflite'
"""