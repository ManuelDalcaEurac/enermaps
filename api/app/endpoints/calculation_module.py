"""Set of endpoints for the management of calculation module.

Calculation modules are long running tasks ran on a raster
with a selection.
"""
import os

from flask import abort, request
from flask_restx import Namespace, Resource

from app.models import calculation_module as CM

api = Namespace("cm", "Calculation module endpoint")
current_file_dir = os.path.dirname(os.path.abspath(__file__))


@api.route("/")
class CMList(Resource):
    def get(self):
        cms = CM.list_cms()

        def cm_as_dict(cm):
            ret = {}
            ret["parameters"] = cm.params
            ret["name"] = cm.name
            ret["pretty_name"] = cm.pretty_name
            ret["schema"] = cm.schema
            return ret

        return {"cms": [cm_as_dict(cm) for cm in cms.values()]}


@api.route("/<string:cm_name>/task")
class TaskCreator(Resource):
    def post(self, cm_name):
        try:
            cm = CM.cm_by_name(cm_name)
        except CM.UnexistantCalculationModule as err:
            abort(404, description=str(err))
        create_task_parameters = request.get_json()
        selection = create_task_parameters.get("selection", {})
        layers = create_task_parameters.get("layers", [])
        parameters = create_task_parameters.get("parameters", {})
        task = cm.call(selection, layers, parameters)
        return {"task_id": task.id}


@api.route("/<string:cm_name>/task/<string:task_id>")
class CM_fakeoutput(Resource):
    def delete(self, cm_name, task_id):
        res = CM.task_by_id(task_id, cm_name=cm_name)
        res.revoke(terminate=True)
        return {"status": res.status}

    def get(self, cm_name, task_id):
        task = CM.task_by_id(task_id, cm_name=cm_name)
        if not task.ready() or task.status == "REVOKED":
            return {"status": task.status}
        try:
            result = task.get(timeout=0.5)
        except Exception as e:
            if task.status == "FAILURE":
                # this is an expected failure
                return {"status": task.status, "result": str(e)}
        return {"status": task.status, "result": result}
