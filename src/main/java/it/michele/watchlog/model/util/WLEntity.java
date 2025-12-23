package it.michele.watchlog.model.util;

import jakarta.persistence.Column;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.SequenceGenerator;
import lombok.*;
import org.hibernate.Hibernate;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.annotations.UpdateTimestamp;
import org.hibernate.type.SqlTypes;

import java.time.OffsetDateTime;
import java.util.Objects;

@Getter
@Setter
@ToString
@RequiredArgsConstructor
public class WLEntity {

    @jakarta.persistence.Id
    @GeneratedValue(
            strategy = GenerationType.SEQUENCE,
            generator = "hibernate_sequence"
    )
    @SequenceGenerator(
            name = "hibernate_sequence",
            allocationSize = 1
    )
    @org.eclipse.microprofile.graphql.Id
    private Long id;

    @Setter(AccessLevel.NONE)
    @Column(name = "create_date")
    @JdbcTypeCode(SqlTypes.TIMESTAMP)
    @CreationTimestamp
    private OffsetDateTime createDate;

    @Setter(AccessLevel.NONE)
    @Column(name = "modified_date")
    @JdbcTypeCode(SqlTypes.TIMESTAMP)
    @UpdateTimestamp
    private OffsetDateTime modifiedDate;

    @Override
    public boolean equals(Object o) {
        if (this == o) {
            return true;
        }
        if (o == null || Hibernate.getClass(this) !=
                Hibernate.getClass(o)) {
            return false;
        }
        WLEntity wlEntity = (WLEntity) o;
        return id != null && Objects.equals(id, wlEntity.id);
    }

    @Override
    public int hashCode() {
        return getClass().hashCode();
    }
}
