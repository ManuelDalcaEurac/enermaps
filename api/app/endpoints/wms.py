import os

import mapnik
from flask import Response, abort, current_app, request
from flask_restx import Namespace, Resource
from lxml import etree

import app.models.geofile as geofile
import app.common.xml as xml

MIME_TO_MAPNIK = {"image/png": "png", "image/jpg": "jpg"}

api = Namespace("wms", "WMS compatible endpoint")
current_file_dir = os.path.dirname(os.path.abspath(__file__))


def parse_envelope(params):
    raw_extremas = params["bbox"].split(",")
    if len(raw_extremas) != 4:
        raise Exception()
    bbox = [float(extrema) for extrema in raw_extremas]
    bbox_dim = (bbox[0], bbox[1], bbox[2], bbox[3])
    bbox = mapnik.Box2d(*bbox_dim)
    return bbox


def parse_layers(params):
    raw_layers = params["layers"]
    layers = raw_layers.split(",")
    # validation
    return layers


def parse_projection(params):
    return params["srs"].lower()


def parse_size(params):
    height = int(params["height"])
    width = int(params["width"])
    if (height * width) > current_app.config["WMS"]["MAX_SIZE"]:
        raise Exception()
    return width, height


def parse_format(params):
    mime_format = params["format"]
    if mime_format not in current_app.config["WMS"]["GETMAP"]["ALLOWED_OUTPUTS"]:
        raise Exception()
    return MIME_TO_MAPNIK[mime_format], mime_format


@api.route("")
# @api.reponse(400, "Couldn't find the requested method")
class WMS(Resource):
    def get(self):
        normalized_args = {k.lower(): v for k, v in request.args.items()}
        service = normalized_args.get("service")
        if service != "WMS":
            return abort(400, 'service parameter needs to be set to "WMS"')
        request_name = normalized_args.get("request")
        if request_name == "GetMap":
            return self.get_map(normalized_args)
        if request_name == "GetCapabilities":
            return self.get_capabilities(normalized_args)
        if request_name == "GetFeatureInfo":
            return self.get_feature_info(normalized_args)
        return abort(
            404, "Couldn't find the requested method, request parameter needs to be set"
        )

    def get_capabilities(self, _):
        """Return an xml description of the capabilities of the current wms set of endpoints

        This method starts with a preexisting xml template parses it then insert dynamic element from the list of layers and from the flaks configuration
        """
        with open(os.path.join(current_file_dir, "capabilities.xml")) as f:
            root = xml.etree_fromstring(f.read())
        root_layer = root.find("Capability/Layer")
        for crs in current_app.config["WMS"]["ALLOWED_PROJECTIONS"]:
            crs_node = etree.Element("CRS")
            crs_node.text = crs.upper()
            root_layer.append(crs_node)

        capabilities = root.findall("Capability//OnlineResource")
        for element in capabilities:
            element.set("{http://www.w3.org/1999/xlink}href", request.base_url)

        layers = geofile.list_layers()
        for layer in layers:
            layer_node = etree.Element("Layer")
            layer_node.set("queryable", "1" if layer.is_queryable else "0")
            # all layers presented by the api are opaque
            layer_node.set("opaque", "0")
            layer_name = etree.Element("Name")
            layer_name.text = layer.name
            layer_node.append(layer_name)
            abstract = etree.Element("Abstract")
            layer_node.append(abstract)
            layer_title = etree.Element("Title")
            layer_title.text = "This is layer {}".format(layer.name)
            layer_node.append(layer_title)

            root_layer.append(layer_node)

        # TODO: add bounding box for each layer
        # TODO: add a reference to a legend and have an endpoint for it

        get_map = root.find("Capability/Request/GetMap")
        for map_format in current_app.config["WMS"]["GETMAP"]["ALLOWED_OUTPUTS"]:
            format_node = etree.Element("Format")
            format_node.text = map_format
            get_map.append(format_node)

        return Response(etree.tostring(root), mimetype="text/xml")

    def get_map(self, normalized_args):
        # miss:
        # bgcolor
        # exceptions
        projection = parse_projection(normalized_args)
        # validate projection
        width, height = parse_size(normalized_args)

        mp = mapnik.Map(width, height, "+init=" + projection)
        # TODO: how do we manage style ? just have hardcoded
        # style list in a dir ?
        s = mapnik.Style()
        r = mapnik.Rule()
        r.symbols.append(mapnik.RasterSymbolizer())
        s.rules.append(r)

        polygon_symbolizer = mapnik.PolygonSymbolizer()
        polygon_symbolizer.fill = mapnik.Color("#a0a0a0")
        polygon_symbolizer.smooth = 1.0  # very smooth
        r.symbols.append(polygon_symbolizer)

        line_symbolizer = mapnik.LineSymbolizer()
        line_symbolizer.stroke = mapnik.Color("black")
        line_symbolizer.stroke_width = 1.0
        r.symbols.append(line_symbolizer)
        s.rules.append(r)

        style_name = "My Style"
        mp.append_style(style_name, s)

        # TODO read the background set it
        # mp.background_color = 'steelblue'

        layer_names = parse_layers(normalized_args)
        for layer_name in layer_names:
            try:
                layer = geofile.load(layer_name)
            except FileNotFoundError as e:
                abort(404, e.strerror)
            mapnik_layer = layer.as_mapnik_layer()
            mapnik_layer.styles.append(style_name)
            mp.layers.append(mapnik_layer)

        mp.zoom_to_box(parse_envelope(normalized_args))
        image = mapnik.Image(width, height)
        mapnik.render(mp, image)
        mapnik_format, mime_format = parse_format(normalized_args)
        return Response(image.tostring(mapnik_format), mimetype=mime_format)

    def get_feature_info(self, normalized_args):
        raise NotImplementedError()
