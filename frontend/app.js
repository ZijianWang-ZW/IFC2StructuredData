import * as THREE from 'https://esm.sh/three@0.161.0';
import { OrbitControls } from 'https://esm.sh/three@0.161.0/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'https://esm.sh/three@0.161.0/examples/jsm/loaders/GLTFLoader.js';
import cytoscape from 'https://esm.sh/cytoscape@3.29.2';

const state = {
  viewerModelUrl: '/viewer-files/model.glb',
  selectedGlobalId: null,
  viewerIndex: {},
  objectTypeMap: {},
  geometryNodeMap: new Map(),
  objectDetailCache: new Map(),
  geometryDetailCache: new Map(),
  neighborhoodCache: new Map(),
  fullGraphCache: null,
  graphMode: 'none',
  currentCenterGlobalId: null,
  currentHops: 1,
  lastNodeTapAt: 0,
  lastNodeTapId: null,
  cy: null,
  scene: null,
  camera: null,
  renderer: null,
  controls: null,
  raycaster: null,
  mouse: null,
  loadedRoot: null,
  objectMap: new Map(),
  selectedMesh: null,
};

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function stringifyForInspector(value) {
  const maxString = 1600;
  return JSON.stringify(
    value,
    (_key, v) => {
      if (typeof v === 'string' && v.length > maxString) {
        return `${v.slice(0, maxString)} ... [truncated ${v.length - maxString} chars]`;
      }
      return v;
    },
    2
  );
}

function setInspector(title, payload) {
  const el = document.getElementById('detailContent');
  if (!el) return;
  const body = typeof payload === 'string' ? payload : stringifyForInspector(payload);
  el.textContent = `${title}\n${body}`;
}

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

async function loadConfig() {
  try {
    const config = await fetchJson('/api/config');
    if (config.viewerModelUrl) state.viewerModelUrl = config.viewerModelUrl;
  } catch (err) {
    console.warn('config fetch failed', err);
  }
}

function initThree() {
  const container = document.getElementById('viewerCanvas');
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf6f9fc);

  const camera = new THREE.PerspectiveCamera(60, container.clientWidth / Math.max(container.clientHeight, 1), 0.1, 50000);
  camera.position.set(20, 20, 20);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  const ambient = new THREE.AmbientLight(0xffffff, 0.75);
  const dir = new THREE.DirectionalLight(0xffffff, 0.8);
  dir.position.set(10, 20, 10);
  scene.add(ambient, dir);

  const grid = new THREE.GridHelper(200, 40, 0x9ca3af, 0xd1d5db);
  scene.add(grid);

  state.scene = scene;
  state.camera = camera;
  state.renderer = renderer;
  state.controls = controls;
  state.raycaster = new THREE.Raycaster();
  state.mouse = new THREE.Vector2();

  function onResize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w <= 0 || h <= 0) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }
  window.addEventListener('resize', onResize);

  renderer.domElement.addEventListener('click', onViewerClick);

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();
}

function focusCameraToObject(obj) {
  if (!obj || !state.camera || !state.controls) return;
  const box = new THREE.Box3().setFromObject(obj);
  if (!isFinite(box.min.x)) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3()).length();
  const dist = Math.max(5, size * 1.2);

  const direction = new THREE.Vector3(1, 1, 1).normalize();
  state.camera.position.copy(center.clone().add(direction.multiplyScalar(dist)));
  state.controls.target.copy(center);
  state.controls.update();
}

function setViewerSelection(globalId) {
  if (state.selectedMesh && state.selectedMesh.userData.__originalMaterial) {
    state.selectedMesh.material = state.selectedMesh.userData.__originalMaterial;
  }
  state.selectedMesh = null;

  if (!globalId) return;
  const rootObj = state.objectMap.get(globalId);
  if (!rootObj) return;
  let obj = rootObj;
  if (!obj.isMesh) {
    let firstMesh = null;
    rootObj.traverse((child) => {
      if (!firstMesh && child.isMesh) firstMesh = child;
    });
    if (!firstMesh) return;
    obj = firstMesh;
  }

  if (!obj.userData.__originalMaterial) {
    obj.userData.__originalMaterial = obj.material;
  }

  const mat = Array.isArray(obj.material)
    ? obj.material.map((m) => m.clone())
    : obj.material.clone();

  const applyHighlight = (m) => {
    if ('emissive' in m) m.emissive.set(0x0066ff);
    if ('emissiveIntensity' in m) m.emissiveIntensity = 0.7;
  };

  if (Array.isArray(mat)) mat.forEach(applyHighlight);
  else applyHighlight(mat);

  obj.material = mat;
  state.selectedMesh = obj;
  focusCameraToObject(rootObj);
}

function findGlobalIdFromIntersection(object) {
  let cur = object;
  while (cur) {
    if (cur.name && state.viewerIndex[cur.name]) return cur.name;
    cur = cur.parent;
  }
  return null;
}

function onViewerClick(event) {
  if (!state.renderer || !state.camera || !state.scene) return;
  const rect = state.renderer.domElement.getBoundingClientRect();
  state.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  state.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  state.raycaster.setFromCamera(state.mouse, state.camera);

  const intersects = state.raycaster.intersectObjects(state.scene.children, true);
  if (!intersects.length) return;
  const gid = findGlobalIdFromIntersection(intersects[0].object);
  if (gid) selectObject(gid, 'viewer');
}

async function loadViewerModel() {
  setText('viewerStatus', `Viewer: loading ${state.viewerModelUrl}`);
  const loader = new GLTFLoader();
  return new Promise((resolve, reject) => {
    loader.load(
      state.viewerModelUrl,
      (gltf) => {
        if (state.loadedRoot) state.scene.remove(state.loadedRoot);
        state.loadedRoot = gltf.scene;
        state.scene.add(gltf.scene);

        state.objectMap.clear();
        gltf.scene.traverse((obj) => {
          if (obj.name && state.viewerIndex[obj.name]) {
            state.objectMap.set(obj.name, obj);
          }
        });

        setText('viewerStatus', `Viewer: mapped ${state.objectMap.size} objects`);
        resolve();
      },
      undefined,
      (err) => {
        setText('viewerStatus', `Viewer load failed: ${err.message || err}`);
        reject(err);
      }
    );
  });
}

function initGraph() {
  state.cy = cytoscape({
    container: document.getElementById('graphCanvas'),
    elements: [],
    hideEdgesOnViewport: true,
    textureOnViewport: true,
    motionBlur: false,
    wheelSensitivity: 0.2,
    pixelRatio: 1,
    style: [
      {
        selector: 'node[type = "building"]',
        style: {
          'background-color': '#0f766e',
          label: 'data(label)',
          'font-size': 10,
          'text-wrap': 'ellipsis',
          'text-max-width': 90,
          color: '#0f172a',
        },
      },
      {
        selector: 'node[type = "geometry"]',
        style: {
          'background-color': '#d97706',
          shape: 'diamond',
          label: 'data(label)',
          'font-size': 10,
          'text-wrap': 'ellipsis',
          'text-max-width': 90,
        },
      },
      {
        selector: 'node.selected',
        style: {
          'border-width': 3,
          'border-color': '#0b5ed7',
        },
      },
      {
        selector: 'edge[type = "relates"]',
        style: {
          'curve-style': 'bezier',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': '#94a3b8',
          'line-color': '#94a3b8',
          width: 1.4,
        },
      },
      {
        selector: 'edge[type = "uses"]',
        style: {
          'line-color': '#f59e0b',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': '#f59e0b',
          'line-style': 'dashed',
          width: 1.2,
        },
      },
      {
        selector: 'edge.selected-edge',
        style: {
          width: 3,
          'line-color': '#2563eb',
          'target-arrow-color': '#2563eb',
        },
      },
    ],
    layout: { name: 'grid' },
  });

  state.cy.on('tap', 'node', async (evt) => {
    const node = evt.target;
    const type = node.data('type');
    const now = Date.now();
    const isDoubleTap = state.lastNodeTapId === node.id() && now - state.lastNodeTapAt < 350;
    state.lastNodeTapAt = now;
    state.lastNodeTapId = node.id();

    if (type === 'building') {
      const gid = node.data('globalId');
      await selectObject(gid, 'graph');
      if (isDoubleTap) {
        await expandNeighborhood(gid);
      }
      return;
    }

    if (type === 'geometry') {
      const defId = Number(node.data('definitionId'));
      highlightGeometryInstances(defId);
      await showGeometryDetails(defId);
    }
  });

  state.cy.on('tap', 'edge', (evt) => {
    const edge = evt.target;
    markEdgeSelection(edge.id());
    showEdgeDetails(edge.data());
  });

  state.cy.on('tap', (evt) => {
    if (evt.target === state.cy) {
      clearEdgeSelection();
    }
  });
}

function graphElementsFromData(payload, { resetMaps = true } = {}) {
  const elements = [];
  const buildingNodes = payload.nodes?.buildingObjects || [];
  const geometryNodes = payload.nodes?.geometryDefinitions || [];
  const relates = payload.edges?.relatesTo || [];
  const uses = payload.edges?.usesGeometry || [];
  const denseMode = buildingNodes.length + geometryNodes.length > 260;

  if (resetMaps) {
    state.objectTypeMap = {};
    state.geometryNodeMap.clear();
  }

  for (const o of buildingNodes) {
    state.objectTypeMap[o.GlobalId] = o.ifcType || '-';
    const label = denseMode
      ? `${o.ifcType || 'Object'}`
      : `${o.ifcType || 'Object'}\n${String(o.GlobalId).slice(-8)}`;
    elements.push({
      data: {
        id: `obj:${o.GlobalId}`,
        type: 'building',
        label,
        globalId: o.GlobalId,
        ifcType: o.ifcType || null,
      },
    });
  }

  for (const g of geometryNodes) {
    const definitionId = Number(g.definitionId);
    state.geometryNodeMap.set(definitionId, g);
    elements.push({
      data: {
        id: `geo:${definitionId}`,
        type: 'geometry',
        label: denseMode ? `G#${definitionId}` : `Geometry#${definitionId}`,
        definitionId,
      },
    });
  }

  for (const e of relates) {
    elements.push({
      data: {
        id: `rel:${e.src}:${e.dst}:${e.relationshipType}`,
        source: `obj:${e.src}`,
        target: `obj:${e.dst}`,
        type: 'relates',
        relationshipType: e.relationshipType || 'RELATES_TO',
      },
    });
  }

  for (const e of uses) {
    elements.push({
      data: {
        id: `use:${e.src}:${e.definitionId}`,
        source: `obj:${e.src}`,
        target: `geo:${e.definitionId}`,
        type: 'uses',
        relationshipType: 'USES_GEOMETRY',
      },
    });
  }

  return elements;
}

function getCurrentHops() {
  return Number(document.getElementById('hopsSelect').value || 1);
}

async function getNeighborhoodPayload(globalId, hops, limit = 500) {
  const key = `${globalId}|${hops}|${limit}`;
  if (state.neighborhoodCache.has(key)) return state.neighborhoodCache.get(key);
  const payload = await fetchJson(`/api/graph/neighborhood?globalId=${encodeURIComponent(globalId)}&hops=${hops}&limit=${limit}`);
  state.neighborhoodCache.set(key, payload);
  return payload;
}

async function getFullGraphPayload(limit = 1000) {
  if (state.fullGraphCache && state.fullGraphCache.limit === limit) {
    return state.fullGraphCache;
  }
  const payload = await fetchJson(`/api/graph/full?limit=${limit}`);
  state.fullGraphCache = payload;
  return payload;
}

function runLayout(mode, focusGlobalId = null) {
  if (!state.cy) return;
  if (mode === 'big') {
    state.cy.layout({
      name: 'grid',
      animate: false,
      fit: true,
      padding: 24,
      avoidOverlap: true,
    }).run();
    return;
  }

  if (mode === 'expand') {
    state.cy.layout({
      name: 'cose',
      animate: false,
      fit: false,
      padding: 20,
      numIter: 120,
      randomize: false,
      idealEdgeLength: 80,
      nodeRepulsion: 250000,
    }).run();
    return;
  }

  const roots = focusGlobalId ? [`obj:${focusGlobalId}`] : undefined;
  state.cy.layout({
    name: 'breadthfirst',
    directed: false,
    spacingFactor: 1.05,
    fit: true,
    padding: 24,
    roots,
    animate: false,
  }).run();
}

function replaceGraph(elements, mode, focusGlobalId = null) {
  state.cy.startBatch();
  state.cy.elements().remove();
  state.cy.add(elements);
  state.cy.endBatch();
  runLayout(mode, focusGlobalId);
  clearEdgeSelection();
}

async function refreshNeighborhood(globalId, { force = false } = {}) {
  const hops = getCurrentHops();
  if (
    !force &&
    state.graphMode === 'neighborhood' &&
    state.currentCenterGlobalId === globalId &&
    state.currentHops === hops
  ) {
    return;
  }

  const payload = await getNeighborhoodPayload(globalId, hops, 500);
  const elements = graphElementsFromData(payload, { resetMaps: true });
  replaceGraph(elements, 'neighborhood', globalId);
  state.graphMode = 'neighborhood';
  state.currentCenterGlobalId = globalId;
  state.currentHops = hops;
  setText(
    'graphStatus',
    `Graph: ${payload.nodes.buildingObjects.length} objects, ${payload.edges.relatesTo.length} relations`
  );
}

async function expandNeighborhood(globalId) {
  const hops = getCurrentHops();
  const payload = await getNeighborhoodPayload(globalId, hops, 500);
  const incoming = graphElementsFromData(payload, { resetMaps: false });
  const existingIds = new Set(state.cy.elements().map((el) => el.id()));
  const toAdd = incoming.filter((el) => !existingIds.has(el.data.id));

  if (!toAdd.length) {
    setText('graphStatus', 'Graph: no new nodes to expand');
    return;
  }

  state.cy.startBatch();
  state.cy.add(toAdd);
  state.cy.endBatch();
  runLayout('expand', globalId);
  markGraphSelection(globalId);
  setText(
    'graphStatus',
    `Graph expanded: +${toAdd.length} elements, now ${state.cy.nodes().length} nodes / ${state.cy.edges().length} edges`
  );
}

async function showBigPicture() {
  const payload = await getFullGraphPayload(1000);
  const elements = graphElementsFromData(payload, { resetMaps: true });
  replaceGraph(elements, 'big');
  state.graphMode = 'big';
  state.currentCenterGlobalId = null;
  setText('graphStatus', `Graph(big): ${payload.nodes.buildingObjects.length} objects, ${payload.edges.relatesTo.length} relations`);
}

function markGraphSelection(globalId) {
  state.cy.nodes().removeClass('selected');
  if (!globalId) return;
  const node = state.cy.getElementById(`obj:${globalId}`);
  if (node && node.length) {
    node.addClass('selected');
    state.cy.center(node);
  }
}

function clearEdgeSelection() {
  state.cy.edges().removeClass('selected-edge');
}

function markEdgeSelection(edgeId) {
  clearEdgeSelection();
  const edge = state.cy.getElementById(edgeId);
  if (edge && edge.length) edge.addClass('selected-edge');
}

function highlightGeometryInstances(definitionId) {
  if (!definitionId) return;
  clearEdgeSelection();
  const edges = state.cy
    .edges()
    .filter((edge) => edge.data('type') === 'uses' && Number(edge.target().data('definitionId')) === Number(definitionId));
  state.cy.nodes().removeClass('selected');
  edges.forEach((edge) => edge.source().addClass('selected'));
}

function parseAttributes(rawObject) {
  if (rawObject?.attributes && typeof rawObject.attributes === 'object') {
    return rawObject.attributes;
  }
  if (typeof rawObject?.attributesJson === 'string' && rawObject.attributesJson) {
    try {
      return JSON.parse(rawObject.attributesJson);
    } catch (err) {
      return { parseError: String(err) };
    }
  }
  return {};
}

async function showBuildingDetails(globalId) {
  try {
    let detail = state.objectDetailCache.get(globalId);
    if (!detail) {
      detail = await fetchJson(`/api/object/${encodeURIComponent(globalId)}`);
      state.objectDetailCache.set(globalId, detail);
    }
    const object = detail.object || {};
    const attributes = parseAttributes(object);
    const usesGeometry = (detail.geometry?.uses_geometry_edges || []).map((edge) => ({
      definitionId: edge.definitionId,
      instanceParamsJson: edge.instanceParamsJson || null,
    }));
    setInspector('Building Node Attributes', {
      nodeType: 'building',
      GlobalId: object.GlobalId || globalId,
      ifcType: object.ifcType || null,
      name: object.name || null,
      hasGeometry: object.hasGeometry,
      geometryMethod: object.geometryMethod || null,
      hasGeometryFilePath: object.hasGeometryFilePath || null,
      viewer: detail.viewer || null,
      usesGeometry,
      attributes,
    });
  } catch (err) {
    setInspector('Building Node Attributes', `Failed to load object detail: ${err.message || err}`);
  }
}

async function showGeometryDetails(definitionId) {
  try {
    let detail = state.geometryDetailCache.get(definitionId);
    if (!detail) {
      detail = await fetchJson(`/api/geometry/${Number(definitionId)}`);
      state.geometryDetailCache.set(definitionId, detail);
    }

    const summary = state.geometryNodeMap.get(Number(definitionId)) || {};
    const connectedObjects = state.cy
      .edges()
      .filter((edge) => edge.data('type') === 'uses' && Number(edge.target().data('definitionId')) === Number(definitionId))
      .map((edge) => edge.source().data('globalId'));

    setInspector('Geometry Node Attributes', {
      nodeType: 'geometry',
      definitionId: Number(definitionId),
      summary,
      connectedObjectIds: connectedObjects,
      geometry: detail.geometry || {},
    });
  } catch (err) {
    setInspector('Geometry Node Attributes', `Failed to load geometry detail: ${err.message || err}`);
  }
}

function showEdgeDetails(edgeData) {
  const name = edgeData.relationshipType || edgeData.type || 'edge';
  setInspector('Edge Attributes', {
    edgeType: edgeData.type || null,
    edgeName: name,
    source: edgeData.source || null,
    target: edgeData.target || null,
    relationshipType: edgeData.relationshipType || null,
  });
}

async function selectObject(globalId, source = 'api') {
  if (!globalId) return;
  state.selectedGlobalId = globalId;
  setText('selectedId', globalId);

  setViewerSelection(globalId);
  markGraphSelection(globalId);
  clearEdgeSelection();

  if (source !== 'graph') {
    await refreshNeighborhood(globalId);
    markGraphSelection(globalId);
  }

  await showBuildingDetails(globalId);
  setText('selectedType', state.objectTypeMap[globalId] || '-');
}

async function loadOverview() {
  try {
    const overview = await fetchJson('/api/graph/overview');
    setText('overviewText', `objects=${overview.building_objects}, edges=${overview.relates_edges}, geoDefs=${overview.geometry_definitions}`);
  } catch (err) {
    setText('overviewText', `Overview failed: ${err.message}`);
  }
}

async function init() {
  initThree();
  initGraph();
  await loadConfig();

  try {
    state.viewerIndex = await fetchJson('/api/viewer/index');
  } catch (err) {
    state.viewerIndex = {};
    console.warn('viewer index load failed', err);
  }

  await loadViewerModel();
  await loadOverview();

  const preferred = Object.keys(state.viewerIndex)[0] || null;
  if (preferred) {
    document.getElementById('globalIdInput').value = preferred;
    await selectObject(preferred, 'api');
  }

  document.getElementById('btnFocus').addEventListener('click', async () => {
    const gid = document.getElementById('globalIdInput').value.trim();
    if (gid) await selectObject(gid, 'api');
  });

  document.getElementById('btnBigPicture').addEventListener('click', async () => {
    await showBigPicture();
  });

  document.getElementById('hopsSelect').addEventListener('change', async () => {
    if (state.selectedGlobalId) {
      await refreshNeighborhood(state.selectedGlobalId, { force: true });
      markGraphSelection(state.selectedGlobalId);
    }
  });

  window.ifcApp = {
    selectObject,
    showBigPicture,
    refreshNeighborhood,
    expandNeighborhood,
    state,
  };
}

init().catch((err) => {
  console.error(err);
  setText('viewerStatus', `Startup failed: ${err.message || err}`);
});
