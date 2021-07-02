#!/usr/bin/env python3
from BaseCM import cm_base as cm_base
from BaseCM import cm_input as cm_input

from heatlearn import heatlearn

app = cm_base.get_default_app("heatlearn")
schema_path = cm_base.get_default_schema_path()


@app.task(base=cm_base.CMBase, bind=True, schema_path=schema_path)
def heat_learn(self, selection: dict, rasters: list, params: dict):
    """This is a calculation module that applies the HeatLearn model.
    If there is no raster, we raise a value error.
    """

    if not rasters:
        raise ValueError("Raster list must be non-empty.")
    if len(rasters) > 1:
        raise ValueError("Please select only one raster for now")
    if "features" not in selection:
        raise ValueError("The selection must be a feature set.")
    if not selection["features"]:
        raise ValueError("The selection must be non-empty.")
    raster_paths = []
    for raster in rasters:
        raster_paths.append(cm_input.get_raster_path(raster))
    self.validate_params(params)

    tile_size = params["tileSize"]
    year = params["year"]
    results = heatlearn(selection, raster_paths, tile_size, year)
    return results


if __name__ == "__main__":
    cm_base.start_app(app)