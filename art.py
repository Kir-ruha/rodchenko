import json
import random


def generate_suprematist_art():
    
    palettes = [
        ['#E41E26', '#000000', '#1A1A1A', '#FFD100'],
        ['#E41E26', '#000000', '#FFFFFF', '#003366'],
        ['#E41E26', '#FF6B35', '#000000', '#FFD100', '#1A1A1A'],
        ['#003366', '#000000', '#4A90D9', '#1A1A1A', '#708090'],
        ['#E41E26', '#FF6B35', '#FFD100', '#000000'],
    ]
    
    palette = random.choice(palettes)
    composition = []
    
    comp_type = random.choice(['diagonal', 'centered', 'scattered', 'layered', 'cross'])
    
    if comp_type == 'diagonal':
        composition.append({
            'type': 'rotated_rect',
            'color': palette[0],
            'x': random.randint(5, 20),
            'y': random.randint(30, 50),
            'width': random.randint(60, 80),
            'height': random.randint(8, 15),
            'angle': random.randint(-45, -25)
        })
        for _ in range(random.randint(2, 4)):
            composition.append({
                'type': random.choice(['rotated_rect', 'rectangle']),
                'color': random.choice(palette),
                'x': random.randint(10, 70),
                'y': random.randint(10, 70),
                'width': random.randint(15, 40),
                'height': random.randint(5, 15),
                'angle': random.randint(-60, 60)
            })
            
    elif comp_type == 'centered':
        main_shape = random.choice(['rectangle', 'circle'])
        composition.append({
            'type': main_shape,
            'color': palette[0],
            'x': random.randint(25, 35),
            'y': random.randint(20, 35),
            'width': random.randint(30, 45),
            'height': random.randint(25, 40),
            'angle': 0
        })
        for _ in range(random.randint(3, 6)):
            composition.append({
                'type': random.choice(['rectangle', 'circle', 'triangle']),
                'color': random.choice(palette[1:]),
                'x': random.randint(5, 85),
                'y': random.randint(5, 80),
                'width': random.randint(8, 20),
                'height': random.randint(8, 20),
                'angle': random.randint(-30, 30)
            })
            
    elif comp_type == 'scattered':
        for _ in range(random.randint(5, 9)):
            shape_type = random.choice(['rectangle', 'circle', 'triangle', 'rotated_rect'])
            size = random.randint(10, 30)
            composition.append({
                'type': shape_type,
                'color': random.choice(palette),
                'x': random.randint(5, 75),
                'y': random.randint(5, 70),
                'width': size,
                'height': size if shape_type == 'circle' else random.randint(8, 30),
                'angle': random.randint(-45, 45) if 'rect' in shape_type else 0
            })
            
    elif comp_type == 'layered':
        base_x, base_y = random.randint(15, 30), random.randint(15, 30)
        for i in range(random.randint(3, 5)):
            offset = i * random.randint(8, 15)
            composition.append({
                'type': 'rectangle',
                'color': palette[i % len(palette)],
                'x': base_x + offset,
                'y': base_y + offset // 2,
                'width': random.randint(25, 45),
                'height': random.randint(20, 35),
                'angle': 0
            })
        for _ in range(random.randint(1, 3)):
            composition.append({
                'type': 'circle',
                'color': palette[0],
                'x': random.randint(50, 80),
                'y': random.randint(10, 60),
                'width': random.randint(10, 20),
                'height': random.randint(10, 20),
                'angle': 0
            })
            
    else:
        center_x, center_y = random.randint(35, 50), random.randint(30, 45)
        composition.append({
            'type': 'rectangle',
            'color': palette[0],
            'x': 5,
            'y': center_y,
            'width': 90,
            'height': random.randint(10, 18),
            'angle': 0
        })
        composition.append({
            'type': 'rectangle',
            'color': random.choice(palette[1:3]),
            'x': center_x,
            'y': 5,
            'width': random.randint(12, 20),
            'height': 85,
            'angle': 0
        })
        for _ in range(random.randint(2, 4)):
            composition.append({
                'type': random.choice(['circle', 'rectangle', 'triangle']),
                'color': random.choice(palette),
                'x': random.randint(5, 80),
                'y': random.randint(5, 75),
                'width': random.randint(8, 18),
                'height': random.randint(8, 18),
                'angle': random.randint(-20, 20)
            })
    
    return json.dumps(composition)


def generate_artwork_title():
    prefixes = [
        'Супрематическая композиция', 
        'Динамические формы', 
        'Геометрическая абстракция', 
        'Цветовой контраст', 
        'Пространственная структура'
    ]
    return f"{random.choice(prefixes)} №{random.randint(1, 1000)}"

