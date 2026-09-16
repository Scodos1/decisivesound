/* ============================================================
   MagicRings — vanilla JS port (no React) of the React Bits
   MagicRings component. Requires THREE.js (r1xx UMD build)
   loaded globally *before* this script.

   Original shader logic is unchanged — only the component
   lifecycle was rewritten from React hooks to a plain factory
   function so it can run in a static HTML/CSS/JS site.
   ============================================================ */
(function (global) {
  "use strict";

  const vertexShader = `
void main() {
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

  const fragmentShader = `
precision highp float;

uniform float uTime, uAttenuation, uLineThickness;
uniform float uBaseRadius, uRadiusStep, uScaleRate;
uniform float uOpacity, uNoiseAmount, uRotation, uRingGap;
uniform float uFadeIn, uFadeOut;
uniform float uMouseInfluence, uHoverAmount, uHoverScale, uParallax, uBurst;
uniform vec2 uResolution, uMouse;
uniform vec3 uColor, uColorTwo;
uniform int uRingCount;

const float HP = 1.5707963;
const float CYCLE = 3.45;

float fade(float t) {
  return t < uFadeIn ? smoothstep(0.0, uFadeIn, t) : 1.0 - smoothstep(uFadeOut, CYCLE - 0.2, t);
}

float ring(vec2 p, float ri, float cut, float t0, float px) {
  float t = mod(uTime + t0, CYCLE);
  float r = ri + t / CYCLE * uScaleRate;
  float d = abs(length(p) - r);
  float a = atan(abs(p.y), abs(p.x)) / HP;
  float th = max(1.0 - a, 0.5) * px * uLineThickness;
  float h = (1.0 - smoothstep(th, th * 1.5, d)) + 1.0;
  d += pow(cut * a, 3.0) * r;
  return h * exp(-uAttenuation * d) * fade(t);
}

void main() {
  float px = 1.0 / min(uResolution.x, uResolution.y);
  vec2 p = (gl_FragCoord.xy - 0.5 * uResolution.xy) * px;
  float cr = cos(uRotation), sr = sin(uRotation);
  p = mat2(cr, -sr, sr, cr) * p;
  p -= uMouse * uMouseInfluence;
  float sc = mix(1.0, uHoverScale, uHoverAmount) + uBurst * 0.3;
  p /= sc;
  vec3 c = vec3(0.0);
  float rcf = max(float(uRingCount) - 1.0, 1.0);
  for (int i = 0; i < 10; i++) {
    if (i >= uRingCount) break;
    float fi = float(i);
    vec2 pr = p - fi * uParallax * uMouse;
    vec3 rc = mix(uColor, uColorTwo, fi / rcf);
    c = mix(c, rc, vec3(ring(pr, uBaseRadius + fi * uRadiusStep, pow(uRingGap, fi), i == 0 ? 0.0 : 2.95 * fi, px)));
  }
  c *= 1.0 + uBurst * 2.0;
  float n = fract(sin(dot(gl_FragCoord.xy + uTime * 100.0, vec2(12.9898, 78.233))) * 43758.5453);
  c += (n - 0.5) * uNoiseAmount;
  gl_FragColor = vec4(c, max(c.r, max(c.g, c.b)) * uOpacity);
}
`;

  const defaults = {
    color: "#A855F7",
    colorTwo: "#6366F1",
    speed: 1,
    ringCount: 6,
    attenuation: 10,
    lineThickness: 2,
    baseRadius: 0.35,
    radiusStep: 0.1,
    scaleRate: 0.1,
    opacity: 1,
    blur: 0,
    noiseAmount: 0.1,
    rotation: 0,
    ringGap: 1.5,
    fadeIn: 0.7,
    fadeOut: 0.5,
    followMouse: false,
    mouseInfluence: 0.2,
    hoverScale: 1.2,
    parallax: 0.05,
    clickBurst: false,
    pauseWhenOffscreen: true,
  };

  /**
   * Mounts a MagicRings canvas into `container` (must be positioned,
   * e.g. position:relative/absolute, with a non-zero size).
   * Returns { destroy(), setOpacity(v) } — call destroy() to tear down
   * the WebGL context and all listeners.
   */
  function create(container, options) {
    const opts = Object.assign({}, defaults, options || {});

    if (!container || !global.THREE) {
      return { destroy() {}, setOpacity() {} };
    }
    const THREE = global.THREE;

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: false });
    } catch (e) {
      return { destroy() {}, setOpacity() {} };
    }

    renderer.setClearColor(0x000000, 0);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";
    if (opts.blur > 0) renderer.domElement.style.filter = `blur(${opts.blur}px)`;
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-0.5, 0.5, 0.5, -0.5, 0.1, 10);
    camera.position.z = 1;

    const uniforms = {
      uTime: { value: 0 },
      uAttenuation: { value: 0 },
      uResolution: { value: new THREE.Vector2() },
      uColor: { value: new THREE.Color() },
      uColorTwo: { value: new THREE.Color() },
      uLineThickness: { value: 0 },
      uBaseRadius: { value: 0 },
      uRadiusStep: { value: 0 },
      uScaleRate: { value: 0 },
      uRingCount: { value: 0 },
      uOpacity: { value: 1 },
      uNoiseAmount: { value: 0 },
      uRotation: { value: 0 },
      uRingGap: { value: 1.6 },
      uFadeIn: { value: 0.5 },
      uFadeOut: { value: 0.75 },
      uMouse: { value: new THREE.Vector2() },
      uMouseInfluence: { value: 0 },
      uHoverAmount: { value: 0 },
      uHoverScale: { value: 1 },
      uParallax: { value: 0 },
      uBurst: { value: 0 },
    };

    const material = new THREE.ShaderMaterial({ vertexShader, fragmentShader, uniforms, transparent: true });
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material);
    scene.add(quad);

    let mouse = [0, 0];
    let smoothMouse = [0, 0];
    let hoverAmount = 0;
    let isHovered = false;
    let burst = 0;
    let visible = true;
    let opacityMultiplier = 1;
    let frameId = null;

    function resize() {
      const w = container.clientWidth || 1;
      const h = container.clientHeight || 1;
      const dpr = Math.min(global.devicePixelRatio || 1, 2);
      renderer.setSize(w, h);
      renderer.setPixelRatio(dpr);
      uniforms.uResolution.value.set(w * dpr, h * dpr);
    }
    resize();
    global.addEventListener("resize", resize);

    let ro = null;
    if ("ResizeObserver" in global) {
      ro = new ResizeObserver(resize);
      ro.observe(container);
    }

    function onMouseMove(e) {
      const rect = container.getBoundingClientRect();
      mouse[0] = (e.clientX - rect.left) / rect.width - 0.5;
      mouse[1] = -((e.clientY - rect.top) / rect.height - 0.5);
    }
    function onMouseEnter() { isHovered = true; }
    function onMouseLeave() { isHovered = false; mouse = [0, 0]; }
    function onClick() { burst = 1; }

    container.addEventListener("mousemove", onMouseMove);
    container.addEventListener("mouseenter", onMouseEnter);
    container.addEventListener("mouseleave", onMouseLeave);
    if (opts.clickBurst) container.addEventListener("click", onClick);

    let io = null;
    if (opts.pauseWhenOffscreen && "IntersectionObserver" in global) {
      io = new IntersectionObserver((entries) => {
        entries.forEach((entry) => { visible = entry.isIntersecting; });
      }, { threshold: 0.05 });
      io.observe(container);
    }

    function animate(t) {
      frameId = global.requestAnimationFrame(animate);
      if (!visible) return;

      smoothMouse[0] += (mouse[0] - smoothMouse[0]) * 0.08;
      smoothMouse[1] += (mouse[1] - smoothMouse[1]) * 0.08;
      hoverAmount += ((isHovered ? 1 : 0) - hoverAmount) * 0.08;
      burst *= 0.95;
      if (burst < 0.001) burst = 0;

      uniforms.uTime.value = t * 0.001 * opts.speed;
      uniforms.uAttenuation.value = opts.attenuation;
      uniforms.uColor.value.set(opts.color);
      uniforms.uColorTwo.value.set(opts.colorTwo);
      uniforms.uLineThickness.value = opts.lineThickness;
      uniforms.uBaseRadius.value = opts.baseRadius;
      uniforms.uRadiusStep.value = opts.radiusStep;
      uniforms.uScaleRate.value = opts.scaleRate;
      uniforms.uRingCount.value = opts.ringCount;
      uniforms.uOpacity.value = opts.opacity * opacityMultiplier;
      uniforms.uNoiseAmount.value = opts.noiseAmount;
      uniforms.uRotation.value = (opts.rotation * Math.PI) / 180;
      uniforms.uRingGap.value = opts.ringGap;
      uniforms.uFadeIn.value = opts.fadeIn;
      uniforms.uFadeOut.value = opts.fadeOut;
      uniforms.uMouse.value.set(smoothMouse[0], smoothMouse[1]);
      uniforms.uMouseInfluence.value = opts.followMouse ? opts.mouseInfluence : 0;
      uniforms.uHoverAmount.value = hoverAmount;
      uniforms.uHoverScale.value = opts.hoverScale;
      uniforms.uParallax.value = opts.parallax;
      uniforms.uBurst.value = opts.clickBurst ? burst : 0;

      renderer.render(scene, camera);
    }
    frameId = global.requestAnimationFrame(animate);

    return {
      setOpacity(v) { opacityMultiplier = v; },
      destroy() {
        global.cancelAnimationFrame(frameId);
        global.removeEventListener("resize", resize);
        if (ro) ro.disconnect();
        if (io) io.disconnect();
        container.removeEventListener("mousemove", onMouseMove);
        container.removeEventListener("mouseenter", onMouseEnter);
        container.removeEventListener("mouseleave", onMouseLeave);
        if (opts.clickBurst) container.removeEventListener("click", onClick);
        if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
        renderer.dispose();
        material.dispose();
      },
    };
  }

  global.MagicRings = { create };
})(window);
