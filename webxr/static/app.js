import * as THREE from "three";
import { GLTFLoader } from "./vendor/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "./vendor/jsm/controls/OrbitControls.js";
import { VRButton } from "./vendor/jsm/webxr/VRButton.js";

const hud = document.getElementById("hud");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x00004d);

const DEFAULT_CAMERA_POSITION = new THREE.Vector3(0, 1.4, 2);
const DEFAULT_CONTROLS_TARGET = new THREE.Vector3(0, 1.2, 0);

const camera = new THREE.PerspectiveCamera(
  60,
  window.innerWidth / window.innerHeight,
  0.01,
  1000,
);
camera.position.copy(DEFAULT_CAMERA_POSITION);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.xr.enabled = true;
document.body.appendChild(renderer.domElement);
document.body.appendChild(VRButton.createButton(renderer));

scene.add(new THREE.HemisphereLight(0xffffff, 0x444466, 1.2));
const directional = new THREE.DirectionalLight(0xffffff, 1.0);
directional.position.set(1, 2, 1);
scene.add(directional);

// rotate: left-drag, zoom: scroll, pan: right-drag -- all on by default.
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.copy(DEFAULT_CONTROLS_TARGET);
controls.update();

let currentModel = null;
let currentFit = null; // {scale, position} computed once per load, reapplied by "reset view"
const loader = new GLTFLoader();

// Fit whatever PyMOL exported (arbitrary molecule size, arbitrary offset from
// its own camera-relative export) to a comfortable hand-held scale in front
// of the viewer. Computed once from the model's own (untransformed) bounds
// right after loading, then just reapplied verbatim on "reset view" -- no
// need to recompute from the model's current (already-transformed) state.
function computeFit(object) {
  const box = new THREE.Box3().setFromObject(object);
  const size = new THREE.Vector3();
  box.getSize(size);
  const center = new THREE.Vector3();
  box.getCenter(center);
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  const targetSize = 0.3;
  const scale = targetSize / maxDim;
  return {
    scale,
    position: new THREE.Vector3(
      -center.x * scale,
      1.2 - center.y * scale,
      -center.z * scale,
    ),
  };
}

function applyFit(object, fit) {
  object.scale.setScalar(fit.scale);
  object.position.copy(fit.position);
}

function loadScene(url) {
  hud.textContent = `loading ${url} ...`;
  loader.load(
    url,
    (gltf) => {
      if (currentModel) {
        currentModel.parent?.remove(currentModel);
      }
      grabbers.length = 0;
      twoHand = null;
      // Measurements are children of the old model (see ensureMeasurementGroup)
      // and get discarded along with it -- rebuilding the scene (molecule/rep/
      // color/setting change) always clears any in-progress or completed
      // measurement, same as it already resets grab/fit state above.
      measurementGroup = null;
      pendingAtom = null;
      if (measureHud) measureHud.textContent = " ";
      currentModel = gltf.scene;
      currentFit = computeFit(currentModel);
      applyFit(currentModel, currentFit);
      scene.add(currentModel);
      hud.textContent = `loaded ${url}`;
    },
    undefined,
    (error) => {
      hud.textContent = `failed to load ${url}: ${error}`;
      console.error(error);
    },
  );
}

function resetView() {
  if (currentModel && currentFit) {
    // model may currently be parented to a controller (mid-grab) -- always
    // reattach to the scene first so the fit position below is world-space.
    scene.attach(currentModel);
    applyFit(currentModel, currentFit);
  }
  grabbers.length = 0;
  twoHand = null;
  camera.position.copy(DEFAULT_CAMERA_POSITION);
  controls.target.copy(DEFAULT_CONTROLS_TARGET);
  controls.update();
}

// --- M7: controller grab / rotate / two-handed scale ---
//
// Single-hand grab: `controller.attach(currentModel)` reparents the model
// under the controller *preserving its current world transform* (three.js
// computes the new local transform from controller.matrixWorld), so from
// then on the model simply inherits the controller's own tracked pose each
// frame for free -- no per-frame math needed for one-handed move/rotate.
//
// Two-handed grab: three.js has no built-in helper for this, so when a
// second controller grabs, the model is detached back to the scene (world
// space) and each frame its scale/rotation/position are driven explicitly
// from the vector between the two controllers -- distance ratio for scale,
// twist of that vector for a rotation delta, midpoint delta for translation.
// This mirrors the Unity project's two-handed XRGrabInteractable scaling.

function buildControllerRay() {
  const geometry = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 0, -1),
  ]);
  const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0x66ccff }));
  line.name = "controller-ray";
  line.scale.z = 5;
  return line;
}

const controllers = [renderer.xr.getController(0), renderer.xr.getController(1)];
controllers.forEach((controller) => {
  controller.add(buildControllerRay());
  controller.addEventListener("selectstart", onSelectStart);
  controller.addEventListener("selectend", onSelectEnd);
  scene.add(controller);
});

const raycaster = new THREE.Raycaster();
const grabbers = []; // controllers currently grabbing currentModel, in grab order
let twoHand = null; // {startDistance, startScale, startMidpoint, startPosition, startAngle, startQuaternion}

function controllerHitsModel(controller) {
  if (!currentModel) return false;
  raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
  raycaster.ray.direction.set(0, 0, -1).transformDirection(controller.matrixWorld);
  return raycaster.intersectObject(currentModel, true).length > 0;
}

function midpoint(a, b) {
  return new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
}

function controllerPositions() {
  return grabbers.map((c) => new THREE.Vector3().setFromMatrixPosition(c.matrixWorld));
}

function onSelectStart(event) {
  const controller = event.target;
  if (grabbers.includes(controller) || !controllerHitsModel(controller)) return;
  grabbers.push(controller);

  if (grabbers.length === 1) {
    controller.attach(currentModel);
  } else if (grabbers.length === 2) {
    // switch from one-hand-attached to two-hand explicit tracking: detach
    // back to world space first so the model isn't fighting the controller
    // parent transform while we drive it manually below.
    scene.attach(currentModel);
    const [posA, posB] = controllerPositions();
    twoHand = {
      startDistance: posA.distanceTo(posB) || 1,
      startScale: currentModel.scale.x,
      startMidpoint: midpoint(posA, posB),
      startPosition: currentModel.position.clone(),
      startAngle: Math.atan2(posB.z - posA.z, posB.x - posA.x),
      startQuaternion: currentModel.quaternion.clone(),
    };
  }
}

function onSelectEnd(event) {
  const controller = event.target;
  const index = grabbers.indexOf(controller);
  if (index === -1) return;
  grabbers.splice(index, 1);
  twoHand = null;

  if (grabbers.length === 1) {
    // one controller still grabbing: resume one-hand attach from wherever
    // the model currently sits (no snap -- attach preserves world transform).
    grabbers[0].attach(currentModel);
  } else if (currentModel && currentModel.parent !== scene) {
    scene.attach(currentModel);
  }
}

function updateTwoHandGrab() {
  if (!twoHand || grabbers.length !== 2) return;
  const [posA, posB] = controllerPositions();
  const distance = posA.distanceTo(posB) || 1;
  const scale = twoHand.startScale * (distance / twoHand.startDistance);
  currentModel.scale.setScalar(scale);

  const angle = Math.atan2(posB.z - posA.z, posB.x - posA.x);
  const deltaRotation = new THREE.Quaternion().setFromAxisAngle(
    new THREE.Vector3(0, 1, 0),
    angle - twoHand.startAngle,
  );
  currentModel.quaternion.multiplyQuaternions(deltaRotation, twoHand.startQuaternion);

  const currentMidpoint = midpoint(posA, posB);
  const midpointDelta = new THREE.Vector3().subVectors(currentMidpoint, twoHand.startMidpoint);
  currentModel.position.addVectors(twoHand.startPosition, midpointDelta);
}

// --- click-to-measure ---
//
// Real per-atom picking without threading a custom atom-ID through the
// batched glyph geometry/glTF export (a real risk not worth taking: the
// mesh_loader pipeline already found vtkGLTFExporter silently drops things
// it doesn't understand, e.g. vtkGlyph3DMapper actors export as empty).
// Instead a raycast hit's *world* point is inverted back into the model's
// own local space via `worldToLocal` -- glTF export bakes real absolute
// PyMOL/PDB Angstrom coordinates straight into vertex positions with no
// extra node transform in between, so this recovers real molecule-space
// coordinates regardless of the model's current fit/grab/scale transform --
// and the server (`/api/pick`) finds the real nearest atom from that point.
//
// Exclusive with orbit-drag rather than trying to distinguish a click from
// a drag-release: toggling measure mode on disables OrbitControls, so every
// click on the canvas is unambiguously a measurement pick.

const measureToggle = document.getElementById("measure-mode");
const measureHud = document.getElementById("measure-hud");
const clearMeasurementsButton = document.getElementById("clear-measurements");
const MARKER_RADIUS = 0.3; // Angstroms -- small relative to a ~1.5A atom radius
const PENDING_COLOR = 0xffee00;
const DONE_COLOR = 0x00e5ff;

let pendingAtom = null; // {index, name, resn, resi, coord, marker}
let measurementGroup = null; // THREE.Group, child of currentModel

function ensureMeasurementGroup() {
  if (!currentModel) return null;
  if (!measurementGroup || measurementGroup.parent !== currentModel) {
    measurementGroup = new THREE.Group();
    measurementGroup.name = "measurements";
    currentModel.add(measurementGroup);
  }
  return measurementGroup;
}

function addMarker(coord, color) {
  const group = ensureMeasurementGroup();
  const geometry = new THREE.SphereGeometry(MARKER_RADIUS, 12, 12);
  // depthTest off + high renderOrder: a marker at an atom's exact center is
  // otherwise always fully enclosed by (and invisible inside) that atom's
  // own much larger sphere, regardless of camera angle. Real PyMOL's own
  // selection indicators are small dots drawn the same way -- ignoring the
  // depth buffer so they show through solid geometry -- not a workaround
  // invented for this project.
  const material = new THREE.MeshBasicMaterial({ color, depthTest: false });
  const marker = new THREE.Mesh(geometry, material);
  marker.position.set(coord[0], coord[1], coord[2]);
  marker.renderOrder = 999;
  group.add(marker);
  return marker;
}

function addLine(coordA, coordB) {
  const group = ensureMeasurementGroup();
  const geometry = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(...coordA),
    new THREE.Vector3(...coordB),
  ]);
  // Same depthTest-off reasoning as addMarker -- a line between two atom
  // centers otherwise runs straight through the molecule's own opaque
  // geometry and would be mostly hidden.
  const material = new THREE.LineBasicMaterial({ color: DONE_COLOR, depthTest: false });
  const line = new THREE.Line(geometry, material);
  line.renderOrder = 999;
  group.add(line);
  return line;
}

function describeAtom(atom) {
  return `${atom.name} (${atom.resn}${atom.resi}${atom.chain ? "/" + atom.chain : ""})`;
}

async function fetchDistance(a, b) {
  const response = await fetch(`/api/distance?atom1=${a.index}&atom2=${b.index}`);
  const data = await response.json();
  if (!data.ok) {
    measureHud.textContent = `distance lookup failed: ${data.error}`;
    return;
  }
  measureHud.textContent = `${describeAtom(a)} ↔ ${describeAtom(b)}: ${data.distance.toFixed(2)} Å`;
}

function handlePickedAtom(atom) {
  if (pendingAtom && pendingAtom.index === atom.index) {
    measureHud.textContent = `${describeAtom(atom)} selected -- click a different atom to measure`;
    return;
  }
  if (!pendingAtom) {
    const marker = addMarker(atom.coord, PENDING_COLOR);
    pendingAtom = { ...atom, marker };
    measureHud.textContent = `${describeAtom(atom)} selected -- click a second atom`;
    return;
  }
  pendingAtom.marker.material.color.setHex(DONE_COLOR);
  addMarker(atom.coord, DONE_COLOR);
  addLine(pendingAtom.coord, atom.coord);
  fetchDistance(pendingAtom, atom);
  pendingAtom = null;
}

async function pickLocalPoint(x, y, z) {
  const response = await fetch(`/api/pick?x=${x}&y=${y}&z=${z}`);
  const atom = await response.json();
  if (!atom.ok) {
    measureHud.textContent = `pick failed: ${atom.error}`;
    return null;
  }
  handlePickedAtom(atom);
  return atom;
}

function onCanvasClick(event) {
  if (!measureToggle.checked || !currentModel) return;
  const rect = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(
    ((event.clientX - rect.left) / rect.width) * 2 - 1,
    -((event.clientY - rect.top) / rect.height) * 2 + 1,
  );
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObject(currentModel, true);
  if (hits.length === 0) return;
  const localPoint = currentModel.worldToLocal(hits[0].point.clone());
  pickLocalPoint(localPoint.x, localPoint.y, localPoint.z);
}

function clearMeasurements() {
  if (measurementGroup) {
    measurementGroup.parent?.remove(measurementGroup);
    measurementGroup = null;
  }
  pendingAtom = null;
  measureHud.textContent = " ";
}

renderer.domElement.addEventListener("click", onCanvasClick);
measureToggle.addEventListener("change", () => {
  controls.enabled = !measureToggle.checked;
  if (!measureToggle.checked && pendingAtom) {
    pendingAtom.marker.material.color.setHex(DONE_COLOR);
    pendingAtom = null;
  }
});
clearMeasurementsButton.addEventListener("click", clearMeasurements);

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

renderer.setAnimationLoop(() => {
  controls.update();
  updateTwoHandGrab();
  renderer.render(scene, camera);
});

// Exposed so the Flask-served page (and Playwright tests) can trigger loads
// without a full page reload -- also used by the molecule/rep switcher below.
window.vrPymolLoadScene = loadScene;
window.vrPymolResetView = resetView;
// for Playwright tests to introspect/drive view + grab state without a real
// WebXR session (no XR device is available in headless Chromium): tests
// position controllers manually and call onSelectStart/onSelectEnd directly.
window.vrPymolDebug = {
  camera,
  controls,
  scene,
  controllers,
  onSelectStart: (i) => onSelectStart({ target: controllers[i] }),
  onSelectEnd: (i) => onSelectEnd({ target: controllers[i] }),
  get grabbers() {
    return grabbers.map((c) => controllers.indexOf(c));
  },
  get model() {
    return currentModel;
  },
  // deterministic measurement testing, bypassing real mouse-event/raycast
  // coordinate math (which real clicks still exercise via onCanvasClick):
  // tests can pass known real PyMOL atom-space coordinates directly.
  pickLocalPoint,
  clearMeasurements,
  get measureHud() {
    return measureHud.textContent;
  },
  get pendingAtom() {
    return pendingAtom ? { ...pendingAtom, marker: undefined } : null;
  },
  get measurementGroup() {
    return measurementGroup;
  },
};

const moleculeSelect = document.getElementById("molecule-select");
const repCheckboxes = Array.from(
  document.querySelectorAll("#rep-checkboxes input[type=checkbox]"),
);
const showHydrogens = document.getElementById("show-hydrogens");
const showWaters = document.getElementById("show-waters");
const colorSelect = document.getElementById("color-select");
const stickRadius = document.getElementById("stick-radius");
const stickRadiusValue = document.getElementById("stick-radius-value");
const sphereScale = document.getElementById("sphere-scale");
const sphereScaleValue = document.getElementById("sphere-scale-value");
const cartoonFlatSheets = document.getElementById("cartoon-flat-sheets");
const cartoonSmoothLoops = document.getElementById("cartoon-smooth-loops");
const bgColor = document.getElementById("bg-color");
const resetViewButton = document.getElementById("reset-view");

// Background is a pure display setting -- real PyMOL's bg_color never
// affects exported geometry either, so this is applied client-side only,
// instantly, with no server round trip.
bgColor.addEventListener("input", () => {
  scene.background = new THREE.Color(bgColor.value);
});

stickRadius.addEventListener("input", () => {
  stickRadiusValue.textContent = Number(stickRadius.value).toFixed(2);
});
sphereScale.addEventListener("input", () => {
  sphereScaleValue.textContent = Number(sphereScale.value).toFixed(2);
});

async function applySelection() {
  const molecule = moleculeSelect.value;
  const reps = repCheckboxes.filter((cb) => cb.checked).map((cb) => cb.value);
  if (reps.length === 0) {
    hud.textContent = "select at least one representation";
    return;
  }
  const rep = reps.join("+");
  const hydrogens = showHydrogens.checked ? 1 : 0;
  const waters = showWaters.checked ? 1 : 0;
  const color = colorSelect.value;
  const cartoonFlatSheetsVal = cartoonFlatSheets.checked ? 1 : 0;
  const cartoonSmoothLoopsVal = cartoonSmoothLoops.checked ? 1 : 0;

  hud.textContent = `switching to ${molecule} / ${rep} ...`;
  const response = await fetch(
    `/api/scene?molecule=${encodeURIComponent(molecule)}` +
      `&rep=${encodeURIComponent(rep)}` +
      `&hydrogens=${hydrogens}&waters=${waters}` +
      `&color=${encodeURIComponent(color)}` +
      `&stick_radius=${stickRadius.value}&sphere_scale=${sphereScale.value}` +
      `&cartoon_flat_sheets=${cartoonFlatSheetsVal}&cartoon_smooth_loops=${cartoonSmoothLoopsVal}`,
  );
  if (!response.ok) {
    hud.textContent = `failed to switch: ${response.status}`;
    return;
  }
  // cache-bust: the server overwrites the same path each time, and the
  // no-store header on /scene.gltf covers most browsers, but GLTFLoader's
  // internal fetch caching is bypassed reliably with a query param too.
  loadScene(`/scene.gltf?t=${Date.now()}`);
}

moleculeSelect.addEventListener("change", applySelection);
repCheckboxes.forEach((cb) => cb.addEventListener("change", applySelection));
showHydrogens.addEventListener("change", applySelection);
showWaters.addEventListener("change", applySelection);
colorSelect.addEventListener("change", applySelection);
// "change" (commits on release), not "input" (fires every drag pixel) --
// rebuilding the scene re-exports the whole molecule server-side, too
// expensive to do on every intermediate slider value.
stickRadius.addEventListener("change", applySelection);
sphereScale.addEventListener("change", applySelection);
cartoonFlatSheets.addEventListener("change", applySelection);
cartoonSmoothLoops.addEventListener("change", applySelection);
resetViewButton.addEventListener("click", resetView);
window.vrPymolApplySelection = applySelection;

loadScene("/scene.gltf");
