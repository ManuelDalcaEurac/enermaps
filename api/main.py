import os
import io
from flask import Flask, safe_join, send_file, Response, send_from_directory, request
from lxml import etree
from PIL import Image
from flask_restx import Api, Resource, abort
from werkzeug.datastructures import FileStorage
from osgeo import osr, gdal
import mapnik

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config["UPLOAD_DIR"] = "/tmp/upload_dir"
app.config["WMS"] = {}
app.config["WMS"]["ALLOWED_PROJECTIONS"] = ["ESPG:3857"]
app.config["WMS"]["MAX_SIZE"] = 1024**2
app.config["WMS"]["GETMAP"] = {}
app.config["WMS"]["GETMAP"]["ALLOWED_OUTPUTS"] = ["image/png", "image/jpg"]
MIME_TO_MAPNIK = {
            "image/png": "png",
            "image/jpg": "jpg"
        }
api = Api(app)

def get_user_upload(user="user"):
    user_dir = safe_join(app.config["UPLOAD_DIR"], user)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

upload_parser = api.parser()
upload_parser.add_argument('file', location='files',
                           type=FileStorage, required=True)

@api.route("/geofile")
class GeoFiles(Resource):
    def get(self):
        user_dir = get_user_upload()
        files = os.listdir(user_dir)
        return {"files": files}

    @api.expect(upload_parser)
    def post(self):
        args = upload_parser.parse_args()
        uploaded_file = args['file']  # This is FileStorage instance
        output_filepath = safe_join(get_user_upload(), uploaded_file.filename)
        uploaded_file.save(output_filepath)
        projection_string = proj4_from_geotiff(output_filepath)
        if not projection_string:
            abort(400, "The uploaded file didn't contain a projection")
        return {"status": "upload succeeded"}

@api.route("/geofile/<string:layer_name>")
class GeoFile(Resource):
    def get(self, layer_name):
        file_path = safe_join(get_user_upload(), layer_name)
        return send_file(file_path, attachment_filename=file_path)

    def delete(self, layer_name):
        file_path = safe_join(get_user_upload(), layer_name)
        os.unlink(file_path)
        return {"status": "deletion successfull"}

@api.route("/stat/<string:layer_name>")
class RasterStats(Resource):
    pass

def parse_layers(normalized_params):
    for layer in normalized_params['layers']:
        return layer

class CRS:
    def __init__(self, namespace, code):
        self.namespace = namespace.lower()
        self.code = int(code)
        self.proj = None

    def __repr__(self):
        return '%s:%s' % (self.namespace, self.code)

    def __eq__(self, other):
        if str(other) == str(self):
            return True
        return False

    def inverse(self, x, y):
        if not self.proj:
            self.proj = Projection('+init=%s:%s' % (self.namespace, self.code))
        return self.proj.inverse(Coord(x, y))

    def forward(self, x, y):
        if not self.proj:
            self.proj = Projection('+init=%s:%s' % (self.namespace, self.code))        
        return self.proj.forward(Coord(x, y))

def proj4_from_geotiff(path):
    raster = gdal.Open(path)
    prj = raster.GetProjection()
    prj = prj.strip()
    if not prj:
        return ""
    srs = osr.SpatialReference(wkt=prj)

    return srs.ExportToProj4()

def parse_envelope(params):
    raw_extremas = params['bbox'].split(',')
    if len(raw_extremas) != 4:
        raise Exception()
    bbox = [float(extrema) for extrema in raw_extremas]
    bbox_dim = (bbox[0], bbox[1], bbox[2], bbox[3])
    if hasattr(mapnik, 'mapnik_version') and mapnik.mapnik_version() >= 800:
        bbox = mapnik.Box2d(*bbox_dim)
    else:
        bbox = mapnik.Envelope(*bbox_dim)
    return bbox

def parse_layers(params):
    raw_layers = params['layers']
    layers = raw_layers.split(",")
    #validation 
    return layers

def parse_projection(params):
    return params['srs'].lower()

def parse_size(params):
    height = int(params["height"])
    width = int(params['width'])
    if (height * width) > app.config["WMS"]["MAX_SIZE"]:
        raise Exception
    return width, height

def parse_format(params):
    mime_format = params['format']
    if mime_format not in app.config["WMS"]["GETMAP"]["ALLOWED_OUTPUTS"]:
        raise Exception
    return MIME_TO_MAPNIK[mime_format], mime_format

@api.route("/wms")
class WMS(Resource):

    def get(self):
        normalized_args= {k.lower(): v for k, v in request.args.items()}
        request_name = normalized_args['request']
        if normalized_args['service'] != 'WMS':
            return 400
        if request_name == 'GetMap':
            return self.getMap(normalized_args)
        if request_name == 'GetCapabilities':
            return self.getCapabilities(normalized_args)
        if request_name == 'GetFeatureInfo':
            return self.getMap(normalized_args)
        return 404

    def getCapabilities(self, normalized_args):
        #start with the xml template that also act as a configuration file
        with open("capabilities.xml") as f:
            root = etree.fromstring(f.read())
        root_layer = root.find('Capability/Layer')
        for crs in app.config["WMS"]["ALLOWED_PROJECTIONS"]:
            crs_node = etree.Element('CRS')
            crs_node.text = crs.upper()
            root_layer.append(crs_node)

        for layer in ["a", "b", "c"]:
            layer_node = etree.Element('Layer')
            layer_node.set("queryable", "1")
            layer_node.set("opaque", "0")
            layer_name= etree.Element("Name")
            layer_name.text = layer
            layer_node.append(layer_name)
            abstract = etree.Element("Abstract")
            layer_node.append(abstract)
            layer_title = etree.Element("Title")
            layer_title.text = "This is layer {}".format(layer)
            layer_node.append(layer_title)



            root_layer.append(layer_node)

        #TODO: add bounding box for each layer
        #TODO: add a reference to a legend and have an endpoint for it

        get_map = root.find('Capability/Request/GetMap')
        for map_format in app.config["WMS"]["GETMAP"]["ALLOWED_OUTPUTS"]:
            format_node = etree.Element("Format")
            format_node.text = map_format
            get_map.append(format_node)

        return Response(etree.tostring(root), mimetype='text/xml')

    def getMap(self, normalized_args):
        #miss:
        #bgcolor
        #exceptions
        print(normalized_args)
        projection = parse_projection(normalized_args)
        #validate projection
        print(request.args)
        width, height = parse_size(normalized_args)

        mp = mapnik.Map(width, height, '+init=' + projection)
        #TODO: how do we manage style ? just have hardcoded style list in a dir ?
        s = mapnik.Style()
        r = mapnik.Rule()
        r.symbols.append(mapnik.RasterSymbolizer())
        s.rules.append(r)
        mp.append_style('My Style', s)

        #TODO read the background set it 
        #mp.background_color = 'steelblue'

        layer_names = parse_layers(normalized_args)
        for layer_name in layer_names:
            #TODO: should match name from query
            layer = mapnik.Layer(layer_name)

            #TODO: extract this from raster in advance !
            layer_path = safe_join(get_user_upload(), layer_name)
            layer.srs = proj4_from_geotiff(layer_path)
            print(layer.srs)
            #TODO: get this from the upload folder, check layer at that point ?
            gdal_source = mapnik.Gdal(file=layer_path)
            layer.datasource = gdal_source
            #layer.minimum_scale_denominator

            layer.styles.append('My Style')
            mp.layers.append(layer)

        mp.zoom_to_box(parse_envelope(normalized_args))
        image = mapnik.Image(width, height)
        mapnik.render(mp, image)
        mapnik_format, mime_format = parse_format(normalized_args)
        return Response(image.tostring('png'), mimetype='image/png')

    def getFeatureInfo(self):
        pass

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')
