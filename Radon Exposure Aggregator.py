import os
from qgis.core import *
from qgis.PyQt.QtCore import QCoreApplication
import time

timestart = time.time()
INPUT_FOLDER = "C:\\Users\\maxge\\Downloads\\London"
OUTPUT_FOLDER = "C:\\Users\\maxge\\Downloads\\London\\reprojected_layers"

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

TARGET_CRS = "EPSG:27700"

project = QgsProject.instance()
project.setCrs(QgsCoordinateReferenceSystem(TARGET_CRS))
project.setEllipsoid("EPSG:7019")

for file in os.listdir(INPUT_FOLDER):
    file_path = os.path.join(INPUT_FOLDER, file)

    if file.endswith(".gpkg"):
        layer = QgsVectorLayer(file_path, "temp", "ogr")
        if not layer.isValid():
            print(f"Skipping invalid GeoPackage file: {file}")
            continue

        gpkg_layers = layer.dataProvider().subLayers()
        for layer_info in gpkg_layers:
            layer_name = layer_info.split("!!::!!")[1]
            sublayer = QgsVectorLayer(
                f"{file_path}|layername={layer_name}", layer_name, "ogr"
            )

            if not sublayer.isValid():
                print(f"Skipping invalid layer: {layer_name} in {file}")
                continue

            output_path = os.path.join(OUTPUT_FOLDER, f"{layer_name}_reprojected.gpkg")

            processing.run(
                "native:reprojectlayer",
                {
                    "INPUT": sublayer,
                    "TARGET_CRS": QgsCoordinateReferenceSystem(TARGET_CRS),
                    "OUTPUT": output_path,
                },
            )
            print(f"Layer Reprojected Successfully: {layer_name} in {file}")

    elif file.endswith(".mbtiles"):
        output_path = os.path.join(
            OUTPUT_FOLDER, f"{os.path.splitext(file)[0]}_reprojected.gpkg"
        )

        try:
            result = subprocess.run(
                [
                    "ogr2ogr",
                    "-f",
                    "GPKG",
                    output_path,
                    file_path,
                    "-t_srs",
                    TARGET_CRS,
                ],
                check=True,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            print(f"MBTiles Reprojected Successfully: {file}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to reproject MBTiles file {file}: {e}")
            print(f"Command output: {e.stdout}")
            print(f"Command error: {e.stderr}")

print("Reprojection process completed!")

TARGET_LAYERS = [
    "Radon_Indicative_Atlas_v3_reprojected.gpkg",
    "parish_reprojected.gpkg",
    "boundary_line_ceremonial_counties_reprojected.gpkg",
]


def load_layer(file_path, layer_name):
    layer = QgsVectorLayer(file_path, layer_name, "ogr")
    if not layer.isValid():
        print(f"Failed to load: {file_path}")
        return None
    project.addMapLayer(layer)
    print(f"Loaded layer: {layer_name}")
    return layer


for file in os.listdir(OUTPUT_FOLDER):
    if file in TARGET_LAYERS:
        file_path = os.path.join(OUTPUT_FOLDER, file)
        layer_name = os.path.splitext(file)[0]
        load_layer(file_path, layer_name)


def get_layer(name):
    layers = QgsProject.instance().mapLayersByName(name)
    if not layers:
        raise ValueError(f"Layer '{name}' not found!")
    return layers[0]


parish_layer = get_layer("parish_reprojected")
radon_layer = get_layer("Radon_Indicative_Atlas_v3_reprojected")
county_layer = get_layer("boundary_line_ceremonial_counties_reprojected")

radon_index = QgsSpatialIndex(radon_layer.getFeatures())
radon_features = {f.id(): f for f in radon_layer.getFeatures()}

field_name = "mean_radon"
if parish_layer.fields().indexFromName(field_name) == -1:
    with edit(parish_layer):
        parish_layer.addAttribute(QgsField(field_name, QVariant.Double))
field_idx = parish_layer.fields().indexFromName(field_name)

total_parishes = parish_layer.featureCount()
print(f"Total parishes to process: {total_parishes}")

try:
    provider = parish_layer.dataProvider()
    provider.enterUpdateMode()
    updates = {}

    for i, parish_feature in enumerate(parish_layer.getFeatures()):
        if i % 100 == 0:
            progress = (i / total_parishes) * 100
            print(f"Processed {i}/{total_parishes} parishes ({progress:.1f}%)")
            QCoreApplication.processEvents()

        parish_geom = parish_feature.geometry()
        intersecting_ids = radon_index.intersects(parish_geom.boundingBox())

        valid_radon_features: list = [
            radon_features[id]
            for id in intersecting_ids
            if radon_features[id].geometry().intersects(parish_geom)
        ]
        parish_area = parish_geom.area()
        if parish_area > 0:
            weighted_sum = sum(
                f["CLASS_MAX"]
                * (f.geometry().intersection(parish_geom).area() / parish_area)
                for f in valid_radon_features
            )
        else:
            weighted_sum: float = 0.0
        mean_value: float = float(weighted_sum if weighted_sum else 0.0)

        updates[parish_feature.id()] = {field_idx: mean_value}

        if i % 1000 == 0 and updates:
            provider.changeAttributeValues(updates)
            updates = {}

        updated_value = parish_layer.getFeature(parish_feature.id())[field_idx]

    if updates:
        provider.changeAttributeValues(updates)

    if not parish_layer.commitChanges():
        raise RuntimeError(f"Commit failed: {parish_layer.commitErrors()}")

except Exception as e:
    print(f"Error occurred: {str(e)}")
    parish_layer.rollBack()
finally:
    if parish_layer.isEditable():
        parish_layer.rollBack()
provider.leaveUpdateMode()
test_feature = next(parish_layer.getFeatures())
print(f"First feature value: {test_feature[field_name]}")

color_ramp_color1 = QColor(0, 255, 0, 100)  # green
color_ramp_color2 = QColor(255, 0, 0, 100)  # red

color_ramp = QgsGradientColorRamp(color_ramp_color1, color_ramp_color2)

renderer = QgsGraduatedSymbolRenderer()
renderer.setClassAttribute(field_name)
renderer.setSourceColorRamp(color_ramp)
renderer.setClassificationMethod(QgsClassificationJenks())
renderer.updateClasses(parish_layer, 100)  # 100 classes, natural breaks by default

parish_layer.setRenderer(renderer)
parish_layer.triggerRepaint()
parish_layer.setOpacity(1.0)

QgsProject.instance().reloadAllLayers()


i = 0
for county_feature in county_layer.getFeatures():
    layout = QgsLayout(project)
    layout.initializeDefaults()
    page = layout.pageCollection().page(0)
    page.setPageSize("A4", QgsLayoutItemPage.Orientation.Landscape)

    i += 1
    # Mask creation
    mask_layer = QgsVectorLayer("Polygon?crs=EPSG:27700", "mask", "memory")
    mask_dp = mask_layer.dataProvider()

    full_extent = parish_layer.extent()
    mask_geom = QgsGeometry.fromRect(full_extent).difference(county_feature.geometry())

    if mask_geom.isEmpty():
        continue

    mask_feature = QgsFeature()
    mask_feature.setGeometry(mask_geom)
    mask_dp.addFeature(mask_feature)
    mask_layer.updateExtents()

    QgsProject.instance().addMapLayer(mask_layer)

    symbol = QgsFillSymbol.createSimple(
        {"color": "255,255,255,255", "outline": "0,0,0,0"}
    )
    mask_layer.renderer().setSymbol(symbol)
    mask_layer.triggerRepaint()

    # Format setup
    page = layout.pageCollection().page(0)
    page_width = page.pageSize().width()
    page_height = page.pageSize().height()
    for item in layout.items():
        if isinstance(item, QgsLayoutItemMap):
            layout.removeItem(item)
    map_item = QgsLayoutItemMap(layout)
    map_item.attemptMove(QgsLayoutPoint(5, 5, QgsUnitTypes.LayoutMillimeters))
    map_item.attemptResize(
        QgsLayoutSize(page_width - 10, page_height - 10, QgsUnitTypes.LayoutMillimeters)
    )
    map_item.zoomToExtent(county_feature.geometry().boundingBox().scaled(1.1))
    map_item.setLayers([mask_layer, parish_layer, county_layer])
    mask_layer.triggerRepaint()
    map_item.refresh()

    # Right now you still cannot use legends to get continuous spectrum legends
    # for vector layers. This is a workaround to get a legend with the same
    # colors as the map.
    gradient_symbol = QgsFillSymbol()
    gradient_symbol.deleteSymbolLayer(0)  # Remove default simple fill
    gradient_layer = QgsGradientFillSymbolLayer(
        color_ramp_color2,
        color_ramp_color1,
        gradientType=QgsGradientFillSymbolLayer.Linear,
    )

    gradient_symbol.appendSymbolLayer(gradient_layer)
    YMIN = page_height * (19 / 20)
    YMAX = page_height * (17 / 20)
    XMIN = page_width * (2 / 100)
    XMAX = page_width * (4 / 100)
    polygon = QPolygonF()
    polygon.append(QPointF(XMIN, YMIN))
    polygon.append(QPointF(XMAX, YMIN))
    polygon.append(QPointF(XMAX, YMAX))
    polygon.append(QPointF(XMIN, YMAX))
    polygon_item = QgsLayoutItemPolygon(polygon, layout)
    polygon_item.setSymbol(gradient_symbol)
    polygon_item.attemptMove(
        QgsLayoutPoint(
            page_width / 10, page_height / 10, QgsUnitTypes.LayoutMillimeters
        )
    )
    layout.addLayoutItem(polygon_item)
    min_label = QgsLayoutItemLabel(layout)
    layout.addLayoutItem(min_label)
    min_label.setText("0.0")
    min_label.attemptMove(
        QgsLayoutPoint(
            page_width / 10,
            page_height / 10 - (YMAX - YMIN) + page_height * (1 / 100),
            # If you don't add quite a bit, it ends up inside the rectangle - why?
            QgsUnitTypes.LayoutMillimeters,
        )
    )
    layout.addLayoutItem(min_label)

    max_label = QgsLayoutItemLabel(layout)
    layout.addLayoutItem(max_label)
    max_label.setText("6.0")
    max_label.attemptMove(
        QgsLayoutPoint(
            page_width / 10,
            page_height / 10 - page_height * (2 / 100),  # see comment above
            QgsUnitTypes.LayoutMillimeters,
        )
    )

    # Scalebar
    scalebar = QgsLayoutItemScaleBar(layout)
    scalebar.setStyle("Single Box")
    scalebar.setUnits(QgsUnitTypes.DistanceKilometers)
    scalebar.setNumberOfSegments(1)
    scalebar.setNumberOfSegmentsLeft(0)
    feature_width_km = (
        county_feature.geometry().boundingBox().width() / 1000.0
    )  # Converts meters to kilometers
    units_per_segment = round(feature_width_km / 5, 2)
    scalebar.setUnitsPerSegment(units_per_segment)
    scalebar.setLinkedMap(map_item)
    scalebar.setUnitLabel("km")
    scalebar_font = QFont("Arial", 8)
    scalebar.setFont(scalebar_font)
    scalebar.update()
    scalebar.attemptMove(
        QgsLayoutPoint(
            page_width / 10, page_height * (0.9), QgsUnitTypes.LayoutMillimeters
        )
    )
    layout.addLayoutItem(scalebar)

    # Title
    title = QgsLayoutItemLabel(layout)
    county_name = (
        county_feature["Name"].replace(" ", "_").replace("/", "-").replace("\n", "")
    )
    title.setText(f"Average parish Radon levels in {county_name}")
    title_font = QFont("Arial", 24)
    title.setFont(title_font)
    title.adjustSizeToText()
    title.setFont(title_font)
    title_width = title.rect().width()
    title.attemptMove(
        QgsLayoutPoint(
            ((page_width / 2) - (title_width / 2)),
            page_height / 100,
            QgsUnitTypes.LayoutMillimeters,
        )
    )
    layout.addLayoutItem(title)

    # Export
    layout.addLayoutItem(map_item)
    map_item.refresh()
    layout.refresh()
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = 300
    exporter = QgsLayoutExporter(layout)
    file_path = f"{OUTPUT_FOLDER}/county_{county_name}.png"
    result = exporter.exportToImage(file_path, settings)

    # Clean up
    QgsProject.instance().removeMapLayer(mask_layer)

    if i == 3:
        break

timeend = time.time()
print(f"Total time taken: {timeend - timestart:.2f} seconds")
