"""Find optional-content groups referenced by a PDF page's drawing commands."""

import pikepdf


def page_layer_ids(page):
    groups = set()
    memberships = set()
    streams = set()

    def add_membership(obj):
        if not isinstance(obj, (pikepdf.Array, pikepdf.Dictionary)):
            return
        if obj.is_indirect:
            if obj.objgen in memberships:
                return
            memberships.add(obj.objgen)
        if isinstance(obj, pikepdf.Array):
            for item in obj:
                add_membership(item)
        elif obj.get("/Type") == pikepdf.Name.OCG:
            groups.add(obj.objgen[0])
        elif obj.get("/Type") == pikepdf.Name.OCMD:
            add_membership(obj.get("/VE", obj.get("/OCGs")))

    def resource(resources, category, name):
        if not isinstance(resources, pikepdf.Dictionary):
            return None
        table = resources.get(category)
        return table.get(name) if isinstance(table, pikepdf.Dictionary) else None

    def visit_object(obj, resources, scope):
        if not isinstance(obj, pikepdf.Stream):
            return
        add_membership(obj.get("/OC"))
        if obj.get("/Subtype") != pikepdf.Name.Form and obj.get("/PatternType") != 1:
            return
        if "/Resources" in obj:
            resources, scope = obj.Resources, obj.objgen
        key = (obj.objgen, scope)
        if key in streams:
            return
        streams.add(key)
        visit_commands(obj, resources, scope)

    def visit_commands(container, resources, scope):
        for args, operator in pikepdf.parse_content_stream(container, "BDC DP Do SCN scn"):
            op = str(operator)
            if op in ("BDC", "DP") and len(args) == 2 and args[0] == pikepdf.Name.OC:
                membership = args[1]
                if isinstance(membership, pikepdf.Name):
                    membership = resource(resources, "/Properties", membership)
                add_membership(membership)
            elif op == "Do" and len(args) == 1 and isinstance(args[0], pikepdf.Name):
                visit_object(resource(resources, "/XObject", args[0]), resources, scope)
            elif op in ("SCN", "scn") and args and isinstance(args[-1], pikepdf.Name):
                visit_object(resource(resources, "/Pattern", args[-1]), resources, scope)

    resources = page.obj.get("/Resources", pikepdf.Dictionary())
    scope = page.obj.objgen
    visit_commands(page, resources, scope)
    for annotation in page.obj.get("/Annots", ()):
        if not isinstance(annotation, pikepdf.Dictionary):
            continue
        add_membership(annotation.get("/OC"))
        appearance = annotation.get("/AP")
        if not isinstance(appearance, pikepdf.Dictionary):
            continue
        normal = appearance.get("/N")
        if isinstance(normal, pikepdf.Dictionary):
            state = annotation.get("/AS")
            normal = normal.get(state) if state is not None else None
        visit_object(normal, resources, scope)

    return groups
