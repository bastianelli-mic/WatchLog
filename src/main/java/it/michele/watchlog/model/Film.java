package it.michele.watchlog.model;

import it.michele.watchlog.model.util.WLEntity;
import jakarta.persistence.Entity;
import lombok.*;

@Entity
@Getter
@Setter
@NoArgsConstructor
@ToString
public class Film extends WLEntity {

    private String title;

    public Film(String title) {
        this.title = title;
    }
}
