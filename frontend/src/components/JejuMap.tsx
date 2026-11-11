import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { MapContainer, Marker, TileLayer, useMapEvents } from "react-leaflet";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

export type Click = { lat: number; lon: number };

// Vite 번들에서는 leaflet 기본 아이콘 경로가 깨지므로 직접 지정한다.
const icon = L.icon({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});

function ClickCatcher({ onPick }: { onPick: (c: Click) => void }) {
  useMapEvents({ click: (e) => onPick({ lat: e.latlng.lat, lon: e.latlng.lng }) });
  return null;
}

export default function JejuMap({ value, onPick }: { value: Click | null; onPick: (c: Click) => void }) {
  return (
    <div className="map-box">
      <MapContainer center={[33.38, 126.55]} zoom={10} style={{ height: 320, width: "100%" }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickCatcher onPick={onPick} />
        {value && <Marker position={[value.lat, value.lon]} icon={icon} />}
      </MapContainer>
      <div className="muted" data-testid="click-info">
        {value ? `선택 위치: ${value.lat.toFixed(4)}, ${value.lon.toFixed(4)}` : "지도를 클릭해 분석할 위치를 고르세요."}
      </div>
    </div>
  );
}
