import os
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'productos.db')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# MODELOS
class Producto(db.Model):
    id = db.Column(db.String, primary_key=True)
    nombre = db.Column(db.String, nullable=False)
    categoria = db.Column(db.String, nullable=False)
    precioUSD = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False)
    imagen = db.Column(db.Text, nullable=True)

class Configuracion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tasa_dolar = db.Column(db.Float, nullable=False, default=0)

# RUTA PRINCIPAL
@app.route('/')
def index():
    return render_template('tienda.html')

# API: Obtener productos
@app.route('/api/productos', methods=['GET'])
def get_productos():
    productos = Producto.query.all()
    return jsonify([
        {
            'id': p.id,
            'nombre': p.nombre,
            'categoria': p.categoria,
            'precioUSD': p.precioUSD,
            'stock': p.stock,
            'imagen': p.imagen
        } for p in productos
    ])

# API: Agregar producto
@app.route('/api/productos', methods=['POST'])
def add_producto():
    data = request.get_json()
    if Producto.query.get(data['id']):
        return jsonify({'error': 'Ya existe un producto con ese ID'}), 400
    producto = Producto(
        id=data['id'],
        nombre=data['nombre'],
        categoria=data['categoria'],
        precioUSD=data['precioUSD'],
        stock=data['stock'],
        imagen=data.get('imagen')
    )
    db.session.add(producto)
    db.session.commit()
    return jsonify({'success': True})

# API: Actualizar producto
@app.route('/api/productos/<id>', methods=['PUT'])
def update_producto(id):
    data = request.get_json()
    producto = Producto.query.get(id)
    if not producto:
        return jsonify({'error': 'Producto no encontrado'}), 404

    if 'nombre' in data:
        producto.nombre = data['nombre']
    if 'categoria' in data:
        producto.categoria = data['categoria']
    if 'precioUSD' in data:
        producto.precioUSD = data['precioUSD']
    if 'stock' in data:
        producto.stock = data['stock']
    if 'imagen' in data:
        producto.imagen = data['imagen']

    db.session.commit()
    return jsonify({'success': True})

# API: Eliminar producto
@app.route('/api/productos/<id>', methods=['DELETE'])
def delete_producto(id):
    producto = Producto.query.get(id)
    if not producto:
        return jsonify({'error': 'Producto no encontrado'}), 404
    db.session.delete(producto)
    db.session.commit()
    return jsonify({'success': True})

# API: Obtener tasa del dólar
@app.route('/api/tasa', methods=['GET'])
def get_tasa():
    conf = Configuracion.query.first()
    return jsonify({'tasa': conf.tasa_dolar if conf else 0})

# API: Actualizar tasa del dólar
@app.route('/api/tasa', methods=['POST'])
def set_tasa():
    data = request.get_json()
    tasa = float(data.get('tasa', 0))
    conf = Configuracion.query.first()
    if not conf:
        conf = Configuracion(tasa_dolar=tasa)
        db.session.add(conf)
    else:
        conf.tasa_dolar = tasa
    db.session.commit()
    return jsonify({'tasa': conf.tasa_dolar})

# INICIALIZACIÓN DE LA BASE DE DATOS
if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists(DB_PATH):
            db.create_all()
        if not Configuracion.query.first():
            db.session.add(Configuracion(tasa_dolar=0))
            db.session.commit()
    app.run(host="0.0.0.0", port=8000, debug=False)
