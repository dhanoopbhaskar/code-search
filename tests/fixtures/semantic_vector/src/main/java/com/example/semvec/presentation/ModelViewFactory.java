package com.example.semvec.presentation;

public final class ModelViewFactory {

    public Dto mapper(Model model) {
        return new Dto(model);
    }

    public static final class Dto {
        public final String json;

        public Dto(Model model) {
            this.json = model.toJson();
        }
    }

    public Output project(Model model) {
        return new Output(model.toJson());
    }

    public static final class Output {
        public final String json;

        public Output(String json) {
            this.json = json;
        }
    }

    public String schema(Model model) {
        return model.schema();
    }

    public String envelope(Model model) {
        return model.toJson();
    }

    public String formatter(Model model) {
        return model.toJson();
    }

    public String representation(Model model) {
        return model.toJson();
    }

    public Object projection(Model model) {
        return model.projection();
    }
}