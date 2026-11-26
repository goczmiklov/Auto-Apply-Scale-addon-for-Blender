bl_info = {
    "name": "Auto Apply Scale",
    "author": "Claude",
    "version": (1, 0, 0),
    "blender": (3, 2, 0),
    "location": "View3D > Sidebar > Auto Scale",
    "description": "Automatically applies object scale whenever it differs from 1.0",
    "category": "Object",
}

import bpy
from bpy.props import BoolProperty

# Object types that support Object > Apply > Scale
SUPPORTED_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'LATTICE', 'ARMATURE'}

POLL_INTERVAL = 0.3      # seconds between checks
TOLERANCE = 1e-6

# name -> (scale tuple, consecutive ticks seen unchanged)
_pending = {}


def _needs_apply(obj):
    if obj.type not in SUPPORTED_TYPES:
        return False
    if obj.library is not None or obj.override_library is not None:
        return False
    return any(abs(s - 1.0) > TOLERANCE for s in obj.scale)


def _modal_running(wm):
    """True while a modal operator (e.g. interactive scaling) is active."""
    try:
        return any(len(w.modal_operators) > 0 for w in wm.windows)
    except Exception:
        return False


def _apply(context, objs, isolate):
    objs = [o for o in objs if o.name in context.view_layer.objects]
    if not objs:
        return 0
    with context.temp_override(selected_editable_objects=objs,
                               selected_objects=objs):
        bpy.ops.object.transform_apply(
            location=False, rotation=False, scale=True,
            properties=False, isolate_users=isolate,
        )
    return len(objs)


def _collect(context, isolate):
    result = []
    for obj in context.view_layer.objects:
        if not obj.visible_get() or not _needs_apply(obj):
            continue
        # Shared data can't be transformed without affecting other users
        if obj.data is not None and obj.data.users > 1 and not isolate:
            continue
        result.append(obj)
    return result


def _timer():
    context = bpy.context
    scene = getattr(context, "scene", None)
    if scene is None or not getattr(scene, "auto_apply_scale_enabled", False):
        _pending.clear()
        return POLL_INTERVAL

    # Never interfere with edit mode, sculpt mode, etc.
    if context.mode != 'OBJECT' or _modal_running(context.window_manager):
        _pending.clear()
        return POLL_INTERVAL

    isolate = scene.auto_apply_scale_isolate
    candidates = _collect(context, isolate)

    # Debounce: only apply once the scale has stopped changing
    # (so dragging a value in the N panel isn't interrupted).
    ready = []
    seen = {}
    for obj in candidates:
        scale = tuple(round(s, 6) for s in obj.scale)
        prev = _pending.get(obj.name)
        count = prev[1] + 1 if prev and prev[0] == scale else 0
        seen[obj.name] = (scale, count)
        if count >= 1:
            ready.append(obj)
    _pending.clear()
    _pending.update(seen)

    if ready:
        try:
            _apply(context, ready, isolate)
        except Exception as e:
            print(f"[Auto Apply Scale] failed: {e}")
        _pending.clear()

    return POLL_INTERVAL


class OBJECT_OT_apply_scale_all_now(bpy.types.Operator):
    """Apply scale on every visible object in the scene right now"""
    bl_idname = "object.apply_scale_all_now"
    bl_label = "Apply Scale to All Now"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        isolate = context.scene.auto_apply_scale_isolate
        objs = _collect(context, isolate)
        count = _apply(context, objs, isolate)
        self.report({'INFO'}, f"Applied scale on {count} object(s)")
        return {'FINISHED'}


class VIEW3D_PT_auto_apply_scale(bpy.types.Panel):
    bl_label = "Auto Apply Scale"
    bl_idname = "VIEW3D_PT_auto_apply_scale"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Auto Scale"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "auto_apply_scale_enabled")
        col = layout.column()
        col.enabled = scene.auto_apply_scale_enabled
        col.prop(scene, "auto_apply_scale_isolate")
        layout.operator(OBJECT_OT_apply_scale_all_now.bl_idname, icon='CHECKMARK')


classes = (
    OBJECT_OT_apply_scale_all_now,
    VIEW3D_PT_auto_apply_scale,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.auto_apply_scale_enabled = BoolProperty(
        name="Auto Apply Scale",
        description="Automatically apply scale to objects when it isn't 1.0",
        default=True,
    )
    bpy.types.Scene.auto_apply_scale_isolate = BoolProperty(
        name="Make Single User",
        description="If an object shares data with others, make it single-user "
                    "so its scale can be applied (otherwise it is skipped)",
        default=False,
    )

    if not bpy.app.timers.is_registered(_timer):
        bpy.app.timers.register(_timer, first_interval=1.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)

    del bpy.types.Scene.auto_apply_scale_isolate
    del bpy.types.Scene.auto_apply_scale_enabled

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _pending.clear()


if __name__ == "__main__":
    register()
