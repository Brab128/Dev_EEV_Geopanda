from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as ctx
import requests
import io
from shapely.geometry import shape

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# --- Providers OSM disponibles ---

OSM_PROVIDERS = {
    "OpenStreetMap.Mapnik": ctx.providers.OpenStreetMap.Mapnik,
    "CartoDB.Positron": ctx.providers.CartoDB.Positron,
    "CartoDB.DarkMatter": ctx.providers.CartoDB.DarkMatter,
    "CartoDB.PositronNoLabels": ctx.providers.CartoDB.PositronNoLabels,
    "CartoDB.DarkMatterNoLabels": ctx.providers.CartoDB.DarkMatterNoLabels,
}

# --- Modèles ---

class Entite(BaseModel):
    code: str
    nom: str = ""
    contour: dict

class Marqueur(BaseModel):
    longitude: float
    latitude: float
    icone: str = "●"
    texte: str = ""
    taille: int = 16
    couleur_texte: str = "black"

class MarqueurEtab(BaseModel):
    longitude: float
    latitude: float
    icone: str = "▲"
    texte: str = ""
    taille: int = 16
    couleur_texte: str = "red"

class CarteEntites(BaseModel):
    entites: List[Entite]
    marqueurs: List[Marqueur] = []
    marqueurs_etab: List[MarqueurEtab] = []
    couleur: str = "#4A90D9"
    couleur_contour: str = "black"
    epaisseur_contour: float = 1.0
    remplissage: bool = True
    fond: str = "white"
    largeur: int = 6
    hauteur: int = 6
    dpi: int = 150
    title: str = ""
    nom: str = ""
    entreprise: str = ""
    date: str = ""
    nb_habitants: int = 0
    fond_osm: bool = False
    osm_provider: str = "OpenStreetMap.Mapnik"

class CarteGeoJSON(BaseModel):
    geojson: dict
    marqueurs: List[Marqueur] = []
    marqueurs_etab: List[MarqueurEtab] = []
    couleur: str = "#4A90D9"
    couleur_contour: str = "black"
    epaisseur_contour: float = 1.0
    remplissage: bool = True
    fond: str = "white"
    largeur: int = 6
    hauteur: int = 6
    dpi: int = 150
    title: str = ""
    nom: str = ""
    entreprise: str = ""
    date: str = ""
    nb_habitants: int = 0
    fond_osm: bool = False
    osm_provider: str = "OpenStreetMap.Mapnik"

# --- Helper : construction du footer ---

def build_footer(entreprise, nom, date, nb_habitants):
    parties = []
    if entreprise:
        parties.append(entreprise)
    if nom:
        parties.append(nom)
    if date:
        parties.append(date)
    if nb_habitants:
        parties.append(f"{nb_habitants:,} habitants".replace(",", "\u00a0"))
    return "  |  ".join(parties)

# --- Helper commun ---

def render_gdf(gdf, marqueurs, marqueurs_etab, couleur, couleur_contour,
               epaisseur_contour, remplissage, fond, largeur, hauteur, dpi,
               title="", footer="", fond_osm=False, osm_provider="OpenStreetMap.Mapnik"):

    fig, ax = plt.subplots(figsize=(largeur, hauteur))
    fig.patch.set_facecolor(fond)
    ax.set_facecolor(fond)

    facecolor = couleur if remplissage else "none"

    if fond_osm:
        # Reprojection en Web Mercator (EPSG:3857) requis par contextily
        gdf_mercator = gdf.to_crs(epsg=3857)
        gdf_mercator.plot(
            ax=ax,
            color=facecolor,
            edgecolor=couleur_contour,
            linewidth=epaisseur_contour,
            alpha=0.5
        )
        provider = OSM_PROVIDERS.get(osm_provider, ctx.providers.OpenStreetMap.Mapnik)
        ctx.add_basemap(ax, source=provider, zoom="auto")
        ax.set_axis_off()

        # Reprojeter les marqueurs en Web Mercator pour les annoter correctement
        import pyproj
        transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        for m in list(marqueurs) + list(marqueurs_etab):
            x, y = transformer.transform(m.longitude, m.latitude)
            ax.annotate(
                text=f"{m.icone} {m.texte}".strip(),
                xy=(x, y),
                fontsize=m.taille,
                color=m.couleur_texte,
                ha="center",
                va="bottom"
            )
    else:
        gdf.plot(ax=ax, color=facecolor, edgecolor=couleur_contour, linewidth=epaisseur_contour)
        for m in list(marqueurs) + list(marqueurs_etab):
            ax.annotate(
                text=f"{m.icone} {m.texte}".strip(),
                xy=(m.longitude, m.latitude),
                fontsize=m.taille,
                color=m.couleur_texte,
                ha="center",
                va="bottom"
            )
        ax.axis("off")

    if title:
        fig.text(
            0.5, 0.97, title,
            ha="center", va="top",
            fontsize=12, fontweight="bold", color="#008EAA"
        )

    if footer:
        fig.add_artist(
            plt.Line2D([0.05, 0.95], [0.045, 0.045],
                       transform=fig.transFigure,
                       color="#cccccc", linewidth=0.8)
        )
        fig.text(
            0.5, 0.01, footer,
            ha="center", va="bottom",
            fontsize=8, color="#E35205", style="italic"
        )

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=dpi, facecolor=fond)
    plt.close()
    return Response(content=buf.getvalue(), media_type="image/png")

# --- Endpoint 1 : liste d'entités (depuis n8n) ---

@app.post("/carte/entites")
def carte_entites(req: CarteEntites):
    rows = [
        {"code": e.code, "nom": e.nom, "geometry": shape(e.contour)}
        for e in req.entites
    ]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    footer = build_footer(req.entreprise, req.nom, req.date, req.nb_habitants)
    return render_gdf(
        gdf, req.marqueurs, req.marqueurs_etab, req.couleur,
        req.couleur_contour, req.epaisseur_contour, req.remplissage,
        req.fond, req.largeur, req.hauteur, req.dpi,
        title=req.title, footer=footer,
        fond_osm=req.fond_osm, osm_provider=req.osm_provider
    )

# --- Endpoint 2 : GeoJSON brut ---

@app.post("/carte")
def carte_geojson(req: CarteGeoJSON):
    geojson = req.geojson
    if geojson.get("type") == "FeatureCollection":
        features = geojson["features"]
    elif geojson.get("type") == "Feature":
        features = [geojson]
    else:
        features = [{"type": "Feature", "geometry": geojson, "properties": {}}]
    gdf = gpd.GeoDataFrame.from_features(features).set_crs("EPSG:4326")
    footer = build_footer(req.entreprise, req.nom, req.date, req.nb_habitants)
    return render_gdf(
        gdf, req.marqueurs, req.marqueurs_etab, req.couleur,
        req.couleur_contour, req.epaisseur_contour, req.remplissage,
        req.fond, req.largeur, req.hauteur, req.dpi,
        title=req.title, footer=footer,
        fond_osm=req.fond_osm, osm_provider=req.osm_provider
    )

# --- Endpoint 3 : département par code INSEE (GET) ---

@app.get("/carte/{code}")
def carte_departement(code: str, couleur: str = "#4A90D9", couleur_contour: str = "black",
                      epaisseur_contour: float = 1.0, remplissage: bool = True,
                      fond: str = "white", fond_osm: bool = False,
                      osm_provider: str = "OpenStreetMap.Mapnik"):
    data = requests.get(
        "https://geo.api.gouv.fr/departements?fields=nom,code&geometry=contour"
    ).json()
    rows = [
        {"code": d["code"], "nom": d.get("nom", ""), "geometry": shape(d["geometry"])}
        for d in data if "geometry" in d
    ]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    dep = gdf[gdf["code"] == code]
    if dep.empty:
        return {"error": f"Département {code} non trouvé"}
    return render_gdf(
        dep, [], [], couleur, couleur_contour, epaisseur_contour,
        remplissage, fond, 6, 6, 150,
        fond_osm=fond_osm, osm_provider=osm_provider
    )