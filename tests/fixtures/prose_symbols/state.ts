export class StateManager {
  private state: Record<string, unknown> = {};

  public set(key: string, value: unknown): void {
    this.state[key] = value;
  }

  public get(key: string): unknown {
    return this.state[key];
  }
}
