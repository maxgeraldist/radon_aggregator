This Python script offers fully automated way to utilize QGIS to reproject layers to the same CRS, aggregate radon exposure per UK parish, color parishes depending on their average exposure, and print the results, one image per county. All the data was found in open access on [OS Data Hub](https://osdatahub.os.uk/).

The features of this script include:

- Full reprojection to a singular CRS
- Aggregation of tile radon exposure using intersections with parishes, with weights depending on the size of the tile and county overlap
- Gradient color rendering
- Map printing with relative elements positioning, compatible with different page sizes
