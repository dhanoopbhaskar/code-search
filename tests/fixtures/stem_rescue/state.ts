export interface StateSnapshot {
  version: number;
  data: string;
}

export class StateManager {
  private snapshot: StateSnapshot | null = null;

  public capture(): void {
    this.snapshot = { version: 1, data: "" };
  }

  public restore(): void {
    this.snapshot = null;
  }
}
