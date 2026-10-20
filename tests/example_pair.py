from pybb import BlackboardController, ComponentSubtractor, ComponentAdder, less_than_3, is_positive


if __name__ == "__main__":
    controller = BlackboardController()
    controller.register_predicate("less_than_3", less_than_3)
    controller.register_predicate("is_positive", is_positive)
    # KS1 may only operate on x, KS2 only on y
    x_fixer = ComponentSubtractor(name="XSubtractor", component="x")
    y_fixer = ComponentAdder(name="YAdder", component="y")
    x_fixer2 = ComponentSubtractor(name="XSubtractor2", component="x")
    y_fixer2 = ComponentAdder(name="YAdder2", component="y")
    for ks in (x_fixer, y_fixer, x_fixer2, y_fixer2):
        controller.add_ks(ks)
    # pair entry: in good standing only when x < 3 AND y > 0
    controller.blackboard.write_entry(
        key="pair1",
        measurement={"x": 5, "y": -2},
        conditions={"x": "less_than_3", "y": "is_positive"})
    # failure path: x=100 is unfixable within 3 attempts
    controller.blackboard.write_entry(
        key="pair2",
        measurement={"x": 100, "y": -1},
        conditions={"x": "less_than_3", "y": "is_positive"})
    # route: KS1 works on x, then KS2 works on y, then the overall pair is evaluated
    controller.route("pair1", [x_fixer, y_fixer])
    controller.route("pair2", [x_fixer2, y_fixer2])
    controller.run()
    print(controller.status())
    print()
    with open("history_pair.txt", "w") as f:
        for key, entry in controller.blackboard.get_history():
            f.write(f"{(key, entry)}\n")
    print("history written to history_pair.txt")
    print("escalate")
    print(controller.blackboard.get_escalate())
