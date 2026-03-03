import * as THREE from 'https://esm.sh/three@0.161.0';
import { OrbitControls } from 'https://esm.sh/three@0.161.0/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'https://esm.sh/three@0.161.0/examples/jsm/loaders/GLTFLoader.js';
import cytoscape from 'https://esm.sh/cytoscape@3.29.2';

const state = {
  viewerModelUrl: '/viewer-files/model.glb',
  selectedGlobalId: null,
  viewerIndex: {},
  objectTypeMap: {},
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
    style: [
      {
        selector: 'node[type = "building"]',
        style: {
          'background-color': '#0f766e',
          'label': 'data(label)',
          'font-size': 10,
          'text-wrap': 'ellipsis',
          'text-max-width': 90,
          'color': '#0f172a',
        },
      },
      {
        selector: 'node[type = "geometry"]',
        style: {
          'background-color': '#d97706',
          'shape': 'diamond',
          'label': 'data(label)',
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
          'width': 1.5,
        },
      },
      {
        selector: 'edge[type = "uses"]',
        style: {
          'line-color': '#f59e0b',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': '#f59e0b',
          'line-style': 'dashed',
          'width': 1.5,
        },
      },
    ],
    layout: { name: 'grid' },
  });

  state.cy.on('tap', 'node', (evt) => {
    const node = evt.target;
    const type = node.data('type');
    if (type === 'building') {
      const gid = node.data('globalId');
      selectObject(gid, 'graph');
    }
    if (type === 'geometry') {
      const defId = node.data('definitionId');
      highlightGeometryInstances(defId);
    }
  });
}

function graphElementsFromData(payload) {
  const elements = [];
  const buildingNodes = payload.nodes?.buildingObjects || [];
  const geometryNodes = payload.nodes?.geometryDefinitions || [];
  const relates = payload.edges?.relatesTo || [];
  const uses = payload.edges?.usesGeometry || [];

  state.objectTypeMap = {};

  for (const o of buildingNodes) {
    state.objectTypeMap[o.GlobalId] = o.ifcType || '-';
    elements.push({
      data: {
        id: `obj:${o.GlobalId}`,
        type: 'building',
        label: `${o.ifcType || 'Object'}\n${o.GlobalId}`,
        globalId: o.GlobalId,
      },
    });
  }

  for (const g of geometryNodes) {
    elements.push({
      data: {
        id: `geo:${g.definitionId}`,
        type: 'geometry',
        label: `Geometry#${g.definitionId}`,
        definitionId: g.definitionId,
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
      },
    });
  }

  return elements;
}

async function refreshNeighborhood(globalId) {
  const hops = Number(document.getElementById('hopsSelect').value || 1);
  const payload = await fetchJson(`/api/graph/neighborhood?globalId=${encodeURIComponent(globalId)}&hops=${hops}&limit=500`);
  const elements = graphElementsFromData(payload);
  state.cy.elements().remove();
  state.cy.add(elements);
  state.cy.layout({ name: 'cose', animate: false, fit: true, padding: 30 }).run();
  setText('graphStatus', `Graph: ${payload.nodes.buildingObjects.length} objects, ${payload.edges.relatesTo.length} relations`);
}

async function showBigPicture() {
  const payload = await fetchJson('/api/graph/full?limit=1000');
  const elements = graphElementsFromData(payload);
  state.cy.elements().remove();
  state.cy.add(elements);
  state.cy.layout({ name: 'cose', animate: false, fit: true, padding: 30 }).run();
  setText('graphStatus', `Graph(big): ${payload.nodes.buildingObjects.length} objects, ${payload.edges.relatesTo.length} relations`);
}

function markGraphSelection(globalId) {
  state.cy.nodes().removeClass('selected');
  if (!globalId) return;
  const node = state.cy.getElementById(`obj:${globalId}`);
  if (node) {
    node.addClass('selected');
    state.cy.center(node);
  }
}

function highlightGeometryInstances(definitionId) {
  if (!definitionId) return;
  const edges = state.cy.edges().filter((edge) => edge.data('type') === 'uses' && Number(edge.target().data('definitionId')) === Number(definitionId));
  state.cy.nodes().removeClass('selected');
  edges.forEach((edge) => edge.source().addClass('selected'));
}

async function selectObject(globalId, source = 'api') {
  if (!globalId) return;
  state.selectedGlobalId = globalId;
  setText('selectedId', globalId);

  setViewerSelection(globalId);
  markGraphSelection(globalId);

  if (source !== 'graph') {
    await refreshNeighborhood(globalId);
    markGraphSelection(globalId);
  }
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

  window.ifcApp = {
    selectObject,
    showBigPicture,
    state,
  };
}

init().catch((err) => {
  console.error(err);
  setText('viewerStatus', `Startup failed: ${err.message || err}`);
});
