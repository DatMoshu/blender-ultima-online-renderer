bl_info = {
    "name": "UO Isometric Renderer",
    "author": "Moshu",
    "version": (1, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > UO Render",
    "description": "Sets up camera and renders 8-directional isometric sprites/animations for Ultima Online.",
    "category": "Render",
}

import bpy
import math
import os
import json
import subprocess
import sys

# --- Update Functions ---
def update_transparency(self, context):
    """Updates the scene transparency setting immediately."""
    context.scene.render.film_transparent = self.use_transparency

def update_background(self, context):
    """Updates the world background color."""
    world = context.scene.world
    if not world:
        return
        
    color = self.background_color
    
    # Handle Node-based worlds (default in modern Blender)
    if world.use_nodes and world.node_tree:
        bg_node = world.node_tree.nodes.get('Background')
        if bg_node:
            bg_node.inputs[0].default_value = (color[0], color[1], color[2], 1.0)
    else:
        # Handle simple color worlds
        world.color = (color[0], color[1], color[2])

# --- Property Group to store settings ---
class UORenderSettings(bpy.types.PropertyGroup):
    resolution_x: bpy.props.IntProperty(
        name="Res X", default=512, min=1, description="Render Width"
    )
    resolution_y: bpy.props.IntProperty(
        name="Res Y", default=512, min=1, description="Render Height"
    )
    ortho_scale: bpy.props.FloatProperty(
        name="Zoom (Scale)", default=7.0, min=0.1, description="Camera Orthographic Scale"
    )
    output_path: bpy.props.StringProperty(
        name="Output Path",
        default="//renders/",
        description="Folder to save renders",
        subtype='DIR_PATH'
    )
    render_animations: bpy.props.BoolProperty(
        name="Render Animation",
        default=False,
        description="If checked, renders the full timeline for each direction."
    )
    # New Settings
    use_transparency: bpy.props.BoolProperty(
        name="Transparent BG",
        default=True,
        description="Toggle transparent background",
        update=update_transparency
    )
    background_color: bpy.props.FloatVectorProperty(
        name="BG Color",
        subtype='COLOR',
        default=(0.0, 0.0, 0.0),
        min=0.0, max=1.0,
        description="World Background Color (used if Transparency is OFF)",
        update=update_background
    )
    create_texture_atlas: bpy.props.BoolProperty(
        name="Create Texture Atlas",
        default=False,
        description="Pack all rendered frames into a single texture atlas with JSON metadata"
    )

# --- Operator: Help Popup ---
class UO_OT_ShowHelp(bpy.types.Operator):
    """Show instructions for UO Isometric Renderer"""
    bl_idname = "uo.show_help"
    bl_label = "How to Use"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Quick Guide", icon='HELP')
        col = box.column(align=True)
        col.label(text="1. Click 'Setup UO Scene'.")
        col.label(text="2. Parent to Anchor: Select your model first, then hold Shift and select the UO_Model_Anchor (the yellow cross axes). Press Ctrl + P and choose Object (Keep Transform).")
        col.label(text="3. IMPORTANT: Rotate Model: Select your model (not the anchor). Press R, Z, 45, Enter.")
        col.label(text="   (Otherwise North looks like North-East)")
        col.label(text="4. Adjust Zoom/Resolution.")
        col.label(text="5. Click 'Render All Directions'.")
        
        box.separator()
        box.label(text="Backgrounds:")
        col = box.column(align=True)
        col.label(text="- Uncheck 'Transparent BG' to use color.")
        col.label(text="- Pick a color in 'World Settings'.")
        
        box.separator()
        box.label(text="Texture Atlas:")
        col = box.column(align=True)
        col.label(text="- Check 'Create Texture Atlas' to pack frames")
        col.label(text="- Pillow auto-installs on first use")
        col.label(text="- Atlas: rows=directions, cols=frames")
        col.separator()
        col.label(text="Manual Pillow install (if auto fails):")
        col.label(text="1. Open Blender's Python console")
        col.label(text="2. Run: import subprocess, sys")
        col.label(text="3. Run: subprocess.check_call(")
        col.label(text="   [sys.executable, '-m', 'pip',")
        col.label(text="   'install', 'Pillow'])")
        col.label(text="4. Restart Blender")

# --- Operator: Setup Scene ---
class UO_OT_SetupScene(bpy.types.Operator):
    """Creates Camera, Lights, and Anchor for UO Perspective"""
    bl_idname = "uo.setup_scene"
    bl_label = "Setup UO Scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.uo_settings
        
        # 1. Setup Render Engine
        scene = context.scene
        # Try EEVEE Next (Blender 4.2+), fall back to EEVEE
        if 'BLENDER_EEVEE_NEXT' in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items:
             scene.render.engine = 'BLENDER_EEVEE_NEXT'
        else:
             scene.render.engine = 'BLENDER_EEVEE'

        scene.render.resolution_x = settings.resolution_x
        scene.render.resolution_y = settings.resolution_y
        
        # Apply initial transparency setting
        scene.render.film_transparent = settings.use_transparency
        
        # 2. Create Anchor
        ANCHOR_NAME = "UO_Model_Anchor"
        if ANCHOR_NAME not in bpy.data.objects:
            bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
            anchor = bpy.context.active_object
            anchor.name = ANCHOR_NAME
        else:
            anchor = bpy.data.objects[ANCHOR_NAME]

        # 3. Setup Camera
        CAMERA_NAME = "UO_Iso_Camera"
        if CAMERA_NAME not in bpy.data.objects:
            bpy.ops.object.camera_add()
            cam = bpy.context.active_object
            cam.name = CAMERA_NAME
            scene.camera = cam
        else:
            cam = bpy.data.objects[CAMERA_NAME]

        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = settings.ortho_scale
        cam.location = (10, -10, 10)
        
        # Magic Angle: 90 - atan(0.5) = 63.435...
        magic_angle_x = math.radians(63.435)
        rotation_z = math.radians(45)
        cam.rotation_euler = (magic_angle_x, 0, rotation_z)

        # 4. Setup Light
        if "UO_Sun" not in bpy.data.objects:
            bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
            sun = bpy.context.active_object
            sun.name = "UO_Sun"
            sun.data.energy = 2.0
            sun.rotation_euler = (math.radians(45), math.radians(15), math.radians(30))

        # 5. Ensure World Exists for Background Color
        if not scene.world:
            new_world = bpy.data.worlds.new("UO_World")
            scene.world = new_world
        
        # Trigger background update to ensure color is set
        update_background(settings, context)

        self.report({'INFO'}, "Scene Setup Complete.")
        return {'FINISHED'}

# --- Texture Atlas Creation ---
def ensure_pillow_installed():
    """
    Attempts to install Pillow if not present.
    Returns (success, message)
    """
    import importlib
    import site
    
    # First, ensure user site-packages is in the path
    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        sys.path.append(user_site)
    
    try:
        from PIL import Image
        return True, "Pillow already installed"
    except ImportError:
        pass
    
    # Try to install Pillow
    print("Pillow not found. Attempting to install...")
    try:
        # Install to user site-packages with --user flag
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--user', 'Pillow'])
        print("Pillow installed successfully!")
        
        # Refresh user site-packages path
        importlib.reload(site)
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            sys.path.insert(0, user_site)
        
        # Invalidate import caches so Python finds the new package
        importlib.invalidate_caches()
        
        # Try importing again
        try:
            from PIL import Image
            return True, "Pillow installed and loaded successfully"
        except ImportError:
            return False, "Pillow installed but import failed. Please restart Blender."
            
    except subprocess.CalledProcessError as e:
        print(f"Failed to install Pillow: {e}")
        return False, f"Auto-install failed: {e}. See 'How to Use' for manual instructions."
    except Exception as e:
        print(f"Error installing Pillow: {e}")
        return False, f"Auto-install failed: {e}. See 'How to Use' for manual instructions."

def create_texture_atlas(render_path, directions, frame_count, res_x, res_y):
    """
    Creates a texture atlas from rendered frames.
    Rows = directions (N, NE, E, SE, S, SW, W, NW)
    Columns = animation frames
    Also generates a JSON metadata file.
    """
    # Ensure Pillow is installed
    install_success, install_msg = ensure_pillow_installed()
    if not install_success:
        return False, install_msg
    
    try:
        from PIL import Image
    except ImportError:
        return False, "Pillow import failed after install. Please restart Blender."
    
    # Atlas dimensions
    atlas_width = res_x * frame_count
    atlas_height = res_y * len(directions)
    
    # Create atlas image (RGBA for transparency support)
    atlas = Image.new('RGBA', (atlas_width, atlas_height), (0, 0, 0, 0))
    
    # Metadata structure
    metadata = {
        "atlas": {
            "width": atlas_width,
            "height": atlas_height
        },
        "frame": {
            "width": res_x,
            "height": res_y
        },
        "directions": [],
        "frames": []
    }
    
    # Process each direction (row)
    for row_idx, (dir_name, _) in enumerate(directions):
        direction_data = {
            "name": dir_name,
            "row": row_idx,
            "y": row_idx * res_y
        }
        metadata["directions"].append(direction_data)
        
        # Process each frame (column)
        for col_idx in range(frame_count):
            # Determine filename based on frame count
            if frame_count == 1:
                filename = f"render_{dir_name}.png"
            else:
                # Frame numbers are 1-indexed in the original renders
                frame_num = col_idx + 1
                filename = f"render_{dir_name}_{frame_num:04d}.png"
            
            filepath = os.path.join(render_path, filename)
            
            if os.path.exists(filepath):
                frame_img = Image.open(filepath).convert('RGBA')
                # Resize if needed (should match, but safety check)
                if frame_img.size != (res_x, res_y):
                    frame_img = frame_img.resize((res_x, res_y), Image.LANCZOS)
                
                # Paste into atlas
                x_pos = col_idx * res_x
                y_pos = row_idx * res_y
                atlas.paste(frame_img, (x_pos, y_pos))
                
                # Add frame metadata
                frame_data = {
                    "direction": dir_name,
                    "frame": col_idx,
                    "row": row_idx,
                    "column": col_idx,
                    "x": x_pos,
                    "y": y_pos,
                    "width": res_x,
                    "height": res_y,
                    "source_file": filename
                }
                metadata["frames"].append(frame_data)
            else:
                print(f"Warning: Could not find {filepath}")
    
    # Save atlas
    atlas_path = os.path.join(render_path, "texture_atlas.png")
    atlas.save(atlas_path, "PNG")
    
    # Save metadata JSON
    json_path = os.path.join(render_path, "texture_atlas.json")
    with open(json_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"Atlas saved to: {atlas_path}")
    print(f"Metadata saved to: {json_path}")
    
    return True, atlas_path

# --- Operator: Render Batch ---
class UO_OT_RenderBatch(bpy.types.Operator):
    """Renders 8 directions (and frames if animation is checked)"""
    bl_idname = "uo.render_batch"
    bl_label = "Render All Directions"

    def execute(self, context):
        scene = context.scene
        settings = scene.uo_settings
        anchor = bpy.data.objects.get("UO_Model_Anchor")
        
        if not anchor:
            self.report({'ERROR'}, "Anchor 'UO_Model_Anchor' not found. Run Setup first.")
            return {'CANCELLED'}

        # Prepare Path
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({'ERROR'}, "Save your .blend file first!")
            return {'CANCELLED'}
            
        base_path = os.path.dirname(blend_path)
        if settings.output_path.startswith("//"):
            render_dir = settings.output_path.replace("//", "")
            full_render_path = os.path.join(base_path, render_dir)
        else:
            full_render_path = settings.output_path

        if not os.path.exists(full_render_path):
            os.makedirs(full_render_path)

        # Direction order for atlas: N first (row 1), then clockwise
        # Rendering order matches atlas row order
        directions = [
            ("N", 180), ("NE", 135), ("E", 90), ("SE", 45),
            ("S", 0), ("SW", 315), ("W", 270), ("NW", 225)
        ]
        
        original_rotation = anchor.rotation_euler.z
        start_frame = scene.frame_start
        end_frame = scene.frame_end
        
        for dir_name, angle_deg in directions:
            anchor.rotation_euler.z = math.radians(angle_deg)
            
            if settings.render_animations:
                for frame in range(start_frame, end_frame + 1):
                    scene.frame_set(frame)
                    filename = f"render_{dir_name}_{frame:04d}.png"
                    scene.render.filepath = os.path.join(full_render_path, filename)
                    bpy.ops.render.render(write_still=True)
            else:
                filename = f"render_{dir_name}.png"
                scene.render.filepath = os.path.join(full_render_path, filename)
                bpy.ops.render.render(write_still=True)
                
            print(f"Finished Direction: {dir_name}")

        anchor.rotation_euler.z = original_rotation
        
        # Create texture atlas if enabled
        if settings.create_texture_atlas:
            frame_count = (end_frame - start_frame + 1) if settings.render_animations else 1
            success, result = create_texture_atlas(
                full_render_path, 
                directions, 
                frame_count,
                settings.resolution_x,
                settings.resolution_y
            )
            if success:
                self.report({'INFO'}, f"Batch Render & Atlas Complete! Atlas: {result}")
            else:
                self.report({'WARNING'}, f"Batch Render Complete. Atlas failed: {result}")
        else:
            self.report({'INFO'}, "Batch Render Complete!")
        
        return {'FINISHED'}

# --- UI Panel ---
class UO_PT_Panel(bpy.types.Panel):
    """Creates a Panel in the View3D UI Sidebar"""
    bl_label = "UO Renderer"
    bl_idname = "UO_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "UO Render"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.uo_settings

        # Help Button
        layout.operator("uo.show_help", icon='QUESTION')
        layout.separator()

        # Configuration Box
        box = layout.box()
        box.label(text="Camera & Output")
        box.prop(settings, "resolution_x")
        box.prop(settings, "resolution_y")
        box.prop(settings, "ortho_scale")
        box.prop(settings, "output_path")

        # World Settings Box
        box = layout.box()
        box.label(text="World Settings")
        box.prop(settings, "use_transparency")
        if not settings.use_transparency:
            box.prop(settings, "background_color")

        # Setup Button
        layout.separator()
        layout.operator("uo.setup_scene", icon='CAMERA_DATA')

        # Render Section
        layout.separator()
        box = layout.box()
        box.label(text="Batch Rendering")
        box.prop(settings, "render_animations")
        
        if settings.render_animations:
            row = box.row()
            row.label(text=f"Frames: {scene.frame_start} to {scene.frame_end}")
        
        box.prop(settings, "create_texture_atlas")
        if settings.create_texture_atlas:
            sub = box.box()
            sub.label(text="Atlas Layout:", icon='TEXTURE')
            sub.label(text="Row 1: N → Frames 1,2,3...")
            sub.label(text="Row 2: NE → Frames 1,2,3...")
            sub.label(text="...continuing clockwise")
            
        box.operator("uo.render_batch", icon='RENDER_ANIMATION')


# --- Registration ---
classes = (
    UORenderSettings,
    UO_OT_SetupScene,
    UO_OT_RenderBatch,
    UO_OT_ShowHelp,
    UO_PT_Panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.uo_settings = bpy.props.PointerProperty(type=UORenderSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.uo_settings

if __name__ == "__main__":
    register()