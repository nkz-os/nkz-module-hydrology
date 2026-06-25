export type DrawingMode = 'Point' | 'LineString' | 'Polygon' | 'off';

export interface DrawingCallbacks {
  onComplete?: (geometry: GeoJSON.Geometry) => void;
  onUpdate?: (geometry: GeoJSON.Geometry) => void;
  onCancel?: () => void;
}

export class DrawingManager {
  private viewer: any;
  private Cesium: any;
  private mode: DrawingMode = 'off';
  private handler: any = null;
  private positions: any[] = [];
  private pointEntities: any[] = [];
  private previewEntity: any = null;
  private callbacks: DrawingCallbacks = {};

  constructor(viewer: any) {
    this.viewer = viewer;
    this.Cesium = (window as any).Cesium;
  }

  start(mode: DrawingMode, callbacks: DrawingCallbacks = {}): void {
    this.cancel();
    this.mode = mode;
    this.callbacks = callbacks;
    this.positions = [];
    this.pointEntities = [];
    this.handler = new (this.Cesium.ScreenSpaceEventHandler)(this.viewer.scene.canvas);
    this.setupHandlers();
  }

  private setupHandlers(): void {
    if (!this.handler) return;
    const Cesium = this.Cesium;

    this.handler.setInputAction((click: any) => {
      const cartesian = this.viewer.scene.pickPosition(click.position);
      if (!Cesium.defined(cartesian)) return;
      this.addPoint(cartesian);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    this.handler.setInputAction((move: any) => {
      if (this.positions.length === 0) return;
      const cartesian = this.viewer.scene.pickPosition(move.endPosition);
      if (!Cesium.defined(cartesian)) return;
      this.updatePreview(cartesian);
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    this.handler.setInputAction(() => {
      this.finish();
    }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
  }

  private addPoint(cartesian: any): void {
    const Cesium = this.Cesium;
    this.positions.push(cartesian);

    // Visual marker
    const point = this.viewer.entities.add({
      position: cartesian,
      point: { pixelSize: 8, color: Cesium.Color.DODGERBLUE },
    });
    this.pointEntities.push(point);

    // For Point mode, finish immediately
    if (this.mode === 'Point') {
      this.finish();
    }
  }

  private updatePreview(cartesian: any): void {
    const Cesium = this.Cesium;
    if (this.previewEntity) {
      this.viewer.entities.remove(this.previewEntity);
    }
    const allPositions = [...this.positions, cartesian];
    if (this.mode === 'LineString') {
      this.previewEntity = this.viewer.entities.add({
        polyline: {
          positions: allPositions,
          material: Cesium.Color.WHITE.withAlpha(0.6),
          width: 2,
        },
      });
    } else if (this.mode === 'Polygon' && allPositions.length >= 2) {
      this.previewEntity = this.viewer.entities.add({
        polygon: {
          hierarchy: new Cesium.PolygonHierarchy(allPositions),
          material: Cesium.Color.DODGERBLUE.withAlpha(0.3),
          outline: true,
          outlineColor: Cesium.Color.DODGERBLUE,
        },
      });
    }
  }

  private finish(): void {
    this.cleanup();
    const geometry = this.toGeoJSON();
    if (geometry && this.callbacks.onComplete) {
      this.callbacks.onComplete(geometry);
    }
    this.mode = 'off';
  }

  cancel(): void {
    this.cleanup();
    this.mode = 'off';
    if (this.callbacks.onCancel) this.callbacks.onCancel();
  }

  private cleanup(): void {
    if (this.handler) {
      this.handler.destroy();
      this.handler = null;
    }
    if (this.previewEntity) {
      this.viewer.entities.remove(this.previewEntity);
      this.previewEntity = null;
    }
    this.pointEntities.forEach((e) => this.viewer.entities.remove(e));
    this.pointEntities = [];
  }

  private toGeoJSON(): GeoJSON.Geometry | null {
    if (this.positions.length < 1) return null;
    const cartographic = this.positions.map((p: any) => {
      const c = this.Cesium.Cartographic.fromCartesian(p);
      return [
        this.Cesium.Math.toDegrees(c.longitude),
        this.Cesium.Math.toDegrees(c.latitude),
        c.height,
      ];
    });

    if (this.mode === 'Point') {
      return { type: 'Point', coordinates: cartographic[0] };
    } else if (this.mode === 'LineString' && cartographic.length >= 2) {
      return { type: 'LineString', coordinates: cartographic };
    } else if (this.mode === 'Polygon' && cartographic.length >= 3) {
      return { type: 'Polygon', coordinates: [[...cartographic, cartographic[0]]] };
    }
    return null;
  }
}
