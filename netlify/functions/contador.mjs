import { getStore } from "@netlify/blobs";

// Contador de cuadros completados hasta los dos ascensos.
//
// Solo se escribe cuando alguien termina las 15 llaves, asi que la mayoria
// de las visitas no gasta nada. La lectura se cachea 60 segundos en el CDN
// de Netlify: casi ninguna visita llega a ejecutar la funcion.

const CLAVE = "completados";

async function leer(store) {
  const v = await store.get(CLAVE);
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

export default async (req) => {
  const store = getStore("contador");

  if (req.method === "POST") {
    const total = (await leer(store)) + 1;
    await store.set(CLAVE, String(total));
    return Response.json({ total }, {
      headers: { "Cache-Control": "no-store" }
    });
  }

  const total = await leer(store);
  return Response.json({ total }, {
    // el CDN sirve la respuesta cacheada y no vuelve a invocar la funcion
    headers: { "Cache-Control": "public, max-age=60, s-maxage=60" }
  });
};

export const config = { path: "/api/contador" };
